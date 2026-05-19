from typing import Any

from pydoover.processor import run_app

from .application import SimDashboardApp
from .app_config import SimDashboardConfig


def handler(event: dict[str, Any], context):
    """Lambda handler entry point."""
    SimDashboardConfig.clear_elements()
    return run_app(
        SimDashboardApp(),
        event,
        context,
    )
