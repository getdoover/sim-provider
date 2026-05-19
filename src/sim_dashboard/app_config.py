from pathlib import Path

from pydoover import config
from pydoover.processor import ExtendedPermissionsConfig


class SimDashboardConfig(config.Schema):
    extended_permissions = ExtendedPermissionsConfig(
        extra_fields=[
            "type__name",
            "solution_installs__display_name",
            "group__id",
            "id",
            "display_name",
        ]
    )

    heavy_user_threshold_mb = config.Integer(
        "Heavy User Threshold (MB)",
        default=500,
        minimum=1,
        description="Month-to-date data usage above which a SIM is highlighted as a heavy user.",
    )

    position = config.ApplicationPosition()


def export():
    SimDashboardConfig.export(
        Path(__file__).parents[2] / "doover_config.json", "sim_dashboard"
    )
