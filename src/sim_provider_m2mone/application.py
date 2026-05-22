"""M2M One SIM provider: reconcile assigned-device SIM cards on a schedule."""
import asyncio
import logging
from typing import Any

from pydoover.processor import Application
from pydoover.models import ScheduleEvent, ManualInvokeEvent, AggregateUpdateEvent

from .app_config import M2MOneSimProviderConfig
from .m2mone_client import LookupStatus, M2MOneClient, M2MOneError, SimLookup

log = logging.getLogger(__name__)

HARDWARE_CHANNEL = "dv-hardware"
SIM_CHANNEL = "sim-card"
USAGE_CHANNEL = "sim-usage-daily"
PROVIDER = "m2mone"
USAGE_HISTORY_DAYS = 30


class M2MOneSimProviderApp(Application):
    config: M2MOneSimProviderConfig
    config_cls = M2MOneSimProviderConfig

    async def on_schedule(self, event: ScheduleEvent):
        await self._scan("schedule")

    async def on_manual_invoke(self, event: ManualInvokeEvent):
        await self._scan("manual_invoke")

    async def on_deployment(self, event: ManualInvokeEvent):
        await self._scan("deployment")

    async def on_aggregate_update(self, event: AggregateUpdateEvent):
        """React in real-time when a permitted device updates its dv-hardware aggregate.

        The integration subscribes to ``dv-hardware`` on every permitted device
        (see ``EgressChannelConfig`` in app_config), so this fires per-device as
        soon as a device's hardware state changes. ``event.channel.agent_id`` is
        the source device (not this integration's own agent).
        """
        if event.channel.name != HARDWARE_CHANNEL:
            return

        agent_id = event.channel.agent_id
        data = event.aggregate.data or {}
        modem = _extract_modem(data)
        iccid = _extract_iccid(data, modem)
        if not iccid:
            log.info("Agent %s dv-hardware update has no SIM ICCID; skipping", agent_id)
            return

        log.info("Agent %s dv-hardware updated (ICCID %s); reconciling", agent_id, iccid)
        async with M2MOneClient(
            base_url=self.config.api_base_url.value,
            username=self.config.api_username.value,
            api_key=self.config.api_key.value,
        ) as client:
            try:
                row = await client.get_sim(iccid)
            except M2MOneError as e:
                log.error("Failed to look up ICCID %s on M2M One: %s; aborting reconcile", iccid, e)
                return
            await self._reconcile_device(agent_id, iccid, modem, row)

    async def _scan(self, trigger: str) -> None:
        devices: list[int] = self.received_deployment_config.get("DEVICE_LIST", []) or []
        log.info("M2M One scan starting (trigger=%s) for %d device(s)", trigger, len(devices))
        if not devices:
            return

        hardware = await self._fetch_hardware(devices)
        log.info(
            "Resolved ICCIDs for %d/%d device(s)",
            sum(1 for iccid, _ in hardware.values() if iccid),
            len(devices),
        )

        async with M2MOneClient(
            base_url=self.config.api_base_url.value,
            username=self.config.api_username.value,
            api_key=self.config.api_key.value,
        ) as client:
            try:
                account_sims = await client.list_sims()
            except M2MOneError as e:
                log.error("Failed to list SIMs from M2M One: %s; aborting scan", e)
                return
            log.info("Account has %d SIM(s) registered", len(account_sims))

            record_usage = bool(self.config.record_data_usage.value)

            async def handle(agent_id: int, iccid: str | None, modem: dict[str, Any]) -> None:
                row = account_sims.get(iccid) if iccid else None
                await self._reconcile_device(agent_id, iccid, modem, row)
                if record_usage and row is not None:
                    await self._write_daily_usage(client, agent_id, row.get("simId"))

            await asyncio.gather(
                *(
                    handle(agent_id, iccid, modem)
                    for agent_id, (iccid, modem) in (
                        (a, hardware.get(a, (None, {}))) for a in devices
                    )
                )
            )

    async def _write_daily_usage(self, client: M2MOneClient, agent_id: int, sim_id: Any) -> None:
        """Fetch the SIM's per-day usage history and write it to the usage channel."""
        if not sim_id:
            return
        try:
            series = await client.get_daily_usage(sim_id, days=USAGE_HISTORY_DAYS)
        except M2MOneError as e:
            log.warning("Failed to fetch daily usage for agent %s (simId %s): %s", agent_id, sim_id, e)
            return

        payload = {
            "provider": PROVIDER,
            "window_days": USAGE_HISTORY_DAYS,
            "daily": series,
        }
        try:
            await self.api.update_channel_aggregate(
                USAGE_CHANNEL, payload, replace_data=True, agent_id=agent_id
            )
        except Exception as e:
            log.warning("Failed to write %s for agent %s: %s", USAGE_CHANNEL, agent_id, e)

    async def _fetch_hardware(
        self, agent_ids: list[int]
    ) -> dict[int, tuple[str | None, dict[str, Any]]]:
        """Pull each device's SIM ICCID and modem block from dv-hardware in one call."""
        empty: dict[int, tuple[str | None, dict[str, Any]]] = {
            agent_id: (None, {}) for agent_id in agent_ids
        }
        try:
            batch = await self.api.fetch_multi_agent_aggregates(HARDWARE_CHANNEL, agent_ids)
        except Exception as e:
            log.warning("Multi-agent fetch of %s failed: %s; falling back to no-op", HARDWARE_CHANNEL, e)
            return empty

        result = dict(empty)
        for entry in batch.results:
            data = entry.aggregate.data or {}
            modem = _extract_modem(data)
            result[int(entry.agent_id)] = (_extract_iccid(data, modem), modem)
        return result

    async def _reconcile_device(
        self,
        agent_id: int,
        iccid: str | None,
        modem: dict[str, Any],
        row: dict[str, Any] | None,
    ) -> None:
        if not iccid:
            log.info("Agent %s has no SIM ICCID in %s; skipping", agent_id, HARDWARE_CHANNEL)
            return

        if row is None:
            # The SIM isn't in this provider's account, so we can't classify it.
            # Still write what the device itself reports about the modem so the
            # SIM stays visible (with its ICCID) on the dashboard as unknown.
            log.info("Agent %s ICCID %s not found in M2M One account", agent_id, iccid)
            lookup = SimLookup(
                iccid=iccid,
                status=LookupStatus.NOT_IN_ACCOUNT,
                details=modem or None,
            )
        else:
            log.info("Agent %s ICCID %s matched in M2M One account", agent_id, iccid)
            lookup = SimLookup(
                iccid=iccid,
                status=LookupStatus.IN_ACCOUNT,
                details=row,
                usage=_extract_usage(row),
            )

        payload = {
            **lookup.to_dict(),
            "provider": PROVIDER,
            "configured_account_id": self.config.account_id.value,
        }

        try:
            await self.api.update_channel_aggregate(
                SIM_CHANNEL, payload, replace_data=True, agent_id=agent_id
            )
            await self.api.create_message(SIM_CHANNEL, payload, agent_id=agent_id)
        except Exception as e:
            log.warning("Failed to write %s for agent %s: %s", SIM_CHANNEL, agent_id, e)


def _extract_modem(data: dict[str, Any]) -> dict[str, Any]:
    """The device-reported modem block from a dv-hardware aggregate."""
    return data.get("modem") or {}


def _extract_iccid(data: dict[str, Any], modem: dict[str, Any]) -> str | None:
    iccid = modem.get("sim_iccid") or data.get("sim_iccid")
    return str(iccid) if iccid else None


def _extract_usage(row: dict[str, Any]) -> dict[str, Any]:
    """Pull the month-to-date counters out of a Jasper SIM row."""
    return {
        "month_to_date_data_mb": row.get("monthToDateDataUsageMB"),
        "month_to_date_sms": row.get("monthToDateSmsUsage"),
        "month_to_date_voice": row.get("monthToDateVoiceUsage"),
        "month_to_date_ussd": row.get("monthToDateUssdUsage"),
        "overage_limit": row.get("overageLimit"),
        "overage_limit_reached": row.get("overageLimitReached"),
    }
