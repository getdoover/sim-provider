"""Org-wide fleet SIM-usage dashboard.

This processor does no aggregation itself — the FleetSimUsageWidget remote
component reads each device's `sim-card` channel directly via
fetch_multi_agent_aggregates and renders totals, top users, and the
per-SIM table client-side. The set of devices to show comes from the
DEVICE_MAP the platform populates in this app's deployment config from
the extended-permissions config.

The processor exists only to host that widget (via the static UI schema) and
to keep the dashboard's own agent looking online whenever it is (re)deployed.
"""
import logging
from datetime import datetime, timezone

from pydoover.models.data.connection import ConnectionDisplay
from pydoover.processor import Application
from pydoover.models import (
    ConnectionStatus,
    ConnectionDetermination,
    DeploymentEvent,
    ConnectionConfig,
    ConnectionType,
)

from .app_config import SimDashboardConfig
from .app_ui import SimDashboardUI

log = logging.getLogger(__name__)


class SimDashboardApp(Application):
    config_cls = SimDashboardConfig
    ui_cls = SimDashboardUI

    async def on_deployment(self, event: DeploymentEvent):
        """Ping the connection on (re)deployment so the dashboard agent stays online."""
        await self.api.ping_connection_at(
            datetime.now(timezone.utc),
            ConnectionStatus.continuous_online_no_ping,
            ConnectionDetermination.online,
            user_agent="sim-provider;sim-dashboard",
        )
        await self.api.update_connection_config(
            ConnectionConfig(ConnectionType.periodic, display=ConnectionDisplay.never)
        )
        log.info(f"Pinged connection for dashboard agent {self.agent_id}")
