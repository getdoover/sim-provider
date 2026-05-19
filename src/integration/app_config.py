from pathlib import Path

from pydoover import config
from pydoover.processor import (
    ExtendedPermissionsConfig,
    ScheduleConfig,
    IngestionEndpointConfig,
)


class M2MOneIntegrationConfig(config.Schema):

    permissions = ExtendedPermissionsConfig()
    schedule = ScheduleConfig(
        description="How often to reconcile assigned-device SIM cards against the M2M One account.",
        allowed_modes=["cron", "rate"],
    )

    account_id = config.String(
        "M2M One Account ID",
        name="account_id",
        description="The numeric account ID this integration is associated with. Used to flag SIMs that don't belong to this account.",
    )
    api_base_url = config.String(
        "API Base URL",
        name="api_base_url",
        description="Jasper Provision API base, no trailing slash. M2M One runs on the older Jasper 'Control Center 2' pod where the REST API lives at /provision/api/v1 (not /rws/api/v1).",
        default="https://m2mone.jasperwireless.com/provision/api/v1",
    )
    api_username = config.String(
        "API Username",
        name="api_username",
        description="Username for HTTP Basic auth against the Control Centre API.",
    )
    api_key = config.String(
        "API Key",
        name="api_key",
        description="Password/API key for HTTP Basic auth against the Control Centre API.",
    )
    fixme = IngestionEndpointConfig(advanced=True)


def export():
    M2MOneIntegrationConfig.export(
        Path(__file__).parents[2] / "doover_config.json", "m2mone_integration"
    )
