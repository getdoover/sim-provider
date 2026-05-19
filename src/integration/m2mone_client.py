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

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Any

import aiohttp

log = logging.getLogger(__name__)

PAGE_SIZE = 50

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
            "in_account": self.status == LookupStatus.IN_ACCOUNT,
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
