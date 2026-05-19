from pathlib import Path

from pydoover import ui


class SimDashboardUI(ui.UI, default_open=True):
    widget = ui.RemoteComponent(
        name="FleetSimUsage",
        display_name="Fleet SIM Usage",
        component_url="$config.app().dv_widget_url",
        scope="SimUsageWidget",
        module="./FleetSimUsageWidget",
        # The dashboard agent's deployment config holds the DEVICE_MAP under
        # this app's key (populated from the extended-permissions config).
        app_key="$config.app().APP_KEY",
    )


def export():
    SimDashboardUI(None, None, None).export(
        Path(__file__).parents[2] / "doover_config.json", "sim_dashboard"
    )
