from typing import Any

from pydoover.processor import run_app

from .application import M2MOneSimProviderApp


def handler(event: dict[str, Any], context):
    """Lambda entrypoint."""
    return run_app(M2MOneSimProviderApp(), event, context)
