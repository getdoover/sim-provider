"""M2M One integration: reconcile assigned-device SIM cards on a schedule."""
import asyncio
import logging
import time
from typing import Any

from pydoover.processor import Application
from pydoover.models import DeploymentEvent, ScheduleEvent

from .app_config import M2MOneIntegrationConfig
from .m2mone_client import LookupStatus, M2MOneClient, M2MOneError, SimLookup

log = logging.getLogger(__name__)

HARDWARE_CHANNEL = "dv-hardware"
SIM_CHANNEL = "m2m-simcard"


class M2MOneIntegrationApplication(Application):
    config: M2MOneIntegrationConfig
    config_cls = M2MOneIntegrationConfig

    async def on_schedule(self, event: ScheduleEvent):
        await self._scan("schedule")

    async def on_deployment(self, event: DeploymentEvent):
        # Re-saving the integration's config in the UI fires a deployment event,
        # so this doubles as an operator-triggered refresh.
        await self._scan("deployment")

    async def _scan(self, trigger: str) -> None:
        devices: list[int] = self.received_deployment_config.get("DEVICE_LIST", []) or []
        log.info("M2M One scan starting (trigger=%s) for %d device(s)", trigger, len(devices))
        if not devices:
            return

        iccids = await self._fetch_iccids(devices)
        log.info("Resolved ICCIDs for %d/%d device(s)", sum(1 for v in iccids.values() if v), len(devices))

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

            await asyncio.gather(
                *(
                    self._reconcile_device(client, agent_id, iccids.get(agent_id), account_sims)
                    for agent_id in devices
                )
            )

    async def _fetch_iccids(self, agent_ids: list[int]) -> dict[int, str | None]:
        """Pull the SIM ICCID out of every device's dv-hardware aggregate in one call."""
        try:
            batch = await self.api.fetch_multi_agent_aggregates(HARDWARE_CHANNEL, agent_ids)
        except Exception as e:
            log.warning("Multi-agent fetch of %s failed: %s; falling back to no-op", HARDWARE_CHANNEL, e)
            return {agent_id: None for agent_id in agent_ids}

        result: dict[int, str | None] = {agent_id: None for agent_id in agent_ids}
        for entry in batch.results:
            data = entry.aggregate.data or {}
            modem = data.get("modem") or {}
            iccid = modem.get("sim_iccid") or data.get("sim_iccid")
            if iccid:
                result[int(entry.agent_id)] = str(iccid)
        return result

    async def _reconcile_device(
        self,
        client: M2MOneClient,
        agent_id: int,
        iccid: str | None,
        account_sims: dict[str, dict[str, Any]],
    ) -> None:
        if not iccid:
            log.info("Agent %s has no SIM ICCID in %s; skipping", agent_id, HARDWARE_CHANNEL)
            return

        row = account_sims.get(iccid)
        if row is None:
            log.info("Agent %s ICCID %s not found in M2M One account", agent_id, iccid)
            lookup = SimLookup(iccid=iccid, status=LookupStatus.NOT_IN_ACCOUNT)
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
            "agent_id": agent_id,
            "checked_at": int(time.time() * 1000),
            "configured_account_id": self.config.account_id.value,
        }

        try:
            await self.api.update_channel_aggregate(
                SIM_CHANNEL, payload, replace_data=True, agent_id=agent_id
            )
            await self.api.create_message(SIM_CHANNEL, payload, agent_id=agent_id)
        except Exception as e:
            log.warning("Failed to write %s for agent %s: %s", SIM_CHANNEL, agent_id, e)


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
