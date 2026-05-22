"""Thin async wrapper for M2M One's Jasper Provision REST API.

M2M One runs on the older Jasper Wireless "Control Center 2" pod, so the REST
API lives at ``/provision/api/v1/...`` — not the newer Cisco DevNet
``/rws/api/v1/...`` API. Only one endpoint is used:

    GET /sims?page=N&limit=50&sort=dateAdded&dir=DESC

Auth is HTTP Basic with the API user's username + API key.

Strategy
--------
The list response embeds month-to-date usage and overage state on every SIM
row, so a single paginated call gives us account membership + plan info +
usage for every SIM — no per-ICCID round-trip needed.
"""
from __future__ import annotations

import json
import logging
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any

import aiohttp

log = logging.getLogger(__name__)

PAGE_SIZE = 50
# Data-traffic CDRs are fetched newest-first and paged until we cross the
# requested window. A heavy SIM can log many records per day, so use a larger
# page than the SIM inventory.
CDR_PAGE_SIZE = 500
MS_PER_DAY = 86_400_000

# M2M One wraps the list under `data`; other Jasper Provision deployments use
# different keys, so we look for any of these and bail if none match.
_LIST_KEYS = ("data", "records", "results", "sims", "devices", "items")


class LookupStatus(str, Enum):
    IN_ACCOUNT = "in_account"
    NOT_IN_ACCOUNT = "not_in_account"
    ERROR = "error"


@dataclass
class SimLookup:
    iccid: str
    status: LookupStatus
    details: dict[str, Any] | None = None
    usage: dict[str, Any] | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "iccid": self.iccid,
            "status": self.status.value,
            "details": self.details,
            "usage": self.usage,
            "error": self.error,
        }


class M2MOneError(Exception):
    """Raised when the Jasper API returns an unexpected error."""


class M2MOneClient:
    def __init__(self, base_url: str, username: str, api_key: str):
        self.base_url = base_url.rstrip("/")
        self._auth = aiohttp.BasicAuth(username, api_key)
        self._session: aiohttp.ClientSession | None = None

    async def __aenter__(self):
        self._session = aiohttp.ClientSession(
            auth=self._auth,
            headers={"Accept": "application/json"},
            timeout=aiohttp.ClientTimeout(total=30),
        )
        return self

    async def __aexit__(self, exc_type, exc, tb):
        if self._session is not None:
            await self._session.close()
            self._session = None

    async def list_sims(self) -> dict[str, dict[str, Any]]:
        """Return every SIM on the account, keyed by ICCID.

        Pages through ``/sims`` until a short page comes back (older Provision
        API has no ``lastPage`` marker, so we stop when we get fewer than
        ``PAGE_SIZE`` rows).
        """
        sims: dict[str, dict[str, Any]] = {}
        page = 1
        while True:
            payload = await self._get(
                "/sims",
                params={
                    "page": page,
                    "limit": PAGE_SIZE,
                    "sort": "dateAdded",
                    "dir": "DESC",
                },
            )
            rows = _extract_list(payload)
            for row in rows:
                iccid = row.get("iccid") or row.get("ICCID")
                if iccid:
                    sims[str(iccid)] = row
            if len(rows) < PAGE_SIZE:
                return sims
            page += 1

    async def get_sim(self, iccid: str) -> dict[str, Any] | None:
        """Look up a single SIM by ICCID, returning its row or ``None``.

        This pod's ``/sims/{iccid}`` path doesn't exist (404) and the obvious
        query params are ignored, but the grid's own server-side filter works:
        ``?search=[{"property":"iccid","value":"<iccid>"}]`` returns just the
        matching SIM (same row shape as ``list_sims``, usage included). An
        unknown ICCID comes back as an empty result, which maps to ``None``.
        """
        payload = await self._get(
            "/sims",
            params={"search": json.dumps([{"property": "iccid", "value": iccid}])},
        )
        for row in _extract_list(payload):
            if str(row.get("iccid") or row.get("ICCID") or "") == iccid:
                return row
        return None

    async def get_daily_usage(self, sim_id: int | str, days: int = 30) -> list[dict[str, float]]:
        """Return per-day data usage for the last ``days`` days as a time series.

        Built from the ``/dataTrafficDetails`` CDR feed (keyed by ``simId``, the
        same id ``get_sim``/``list_sims`` rows carry). Each record has a
        ``recordOpenTime`` (epoch ms) and ``roundedUsageKB``; we bucket those by
        UTC day. The endpoint won't filter by date server-side (those filter
        types 500), so we page newest-first and stop once we cross the window.

        Returns a chronological list of ``{"timestamp": <ms>, "data_mb": <float>}``
        points, where ``timestamp`` is epoch-milliseconds at midnight UTC of the
        day (doover's platform-wide timestamp convention). Only days with usage
        are included.
        """
        cutoff_ms = int((datetime.now(tz=timezone.utc) - timedelta(days=days)).timestamp() * 1000)
        search = json.dumps([{"property": "simId", "type": "LONG_EQUALS", "value": int(sim_id), "id": "simId"}])

        per_day_kb: dict[int, float] = defaultdict(float)
        page = 1
        while True:
            payload = await self._get(
                "/dataTrafficDetails",
                params={
                    "page": page,
                    "limit": CDR_PAGE_SIZE,
                    "sort": "recordOpenTime",
                    "dir": "DESC",
                    "search": search,
                },
            )
            rows = _extract_list(payload)
            reached_cutoff = False
            for row in rows:
                ts = row.get("recordOpenTime") or row.get("recordCloseTime")
                if not isinstance(ts, (int, float)):
                    continue
                ts = int(ts)
                if ts < cutoff_ms:
                    reached_cutoff = True
                    continue
                # Floor to midnight UTC; the epoch is itself midnight-UTC aligned.
                day_ms = ts - (ts % MS_PER_DAY)
                per_day_kb[day_ms] += row.get("roundedUsageKB") or 0.0

            if reached_cutoff or len(rows) < CDR_PAGE_SIZE:
                break
            page += 1

        return [
            {"timestamp": day_ms, "data_mb": round(kb / 1024.0, 3)}
            for day_ms, kb in sorted(per_day_kb.items())
        ]

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        assert self._session is not None, "M2MOneClient must be used as an async context manager"
        url = f"{self.base_url}{path}"
        async with self._session.get(url, params=params) as resp:
            if resp.status >= 400:
                body = await resp.text()
                raise M2MOneError(f"HTTP {resp.status} on {path}: {body[:200]}")
            return await resp.json()


def _extract_list(payload: Any) -> list[dict[str, Any]]:
    """Locate the row list inside a Jasper Provision API response wrapper."""
    if isinstance(payload, list):
        return payload
    if not isinstance(payload, dict):
        return []
    for key in _LIST_KEYS:
        rows = payload.get(key)
        if isinstance(rows, list):
            return rows
    return []
