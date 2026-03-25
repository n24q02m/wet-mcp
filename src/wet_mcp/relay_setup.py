"""Zero-env-config relay setup flow for wet-mcp.

wet-mcp works out of the box with local ONNX mode.
Relay is only needed for proxy/sdk modes -- NOT auto-triggered.
"""

from __future__ import annotations

import os
import sys

from loguru import logger


DEFAULT_RELAY_URL = "https://wet-mcp.n24q02m.com"


def load_config_from_file() -> dict[str, str] | None:
    """Try to load config from encrypted config file. Returns None if not found."""
    try:
        from mcp_relay_core.storage.config_file import read_config
        import asyncio

        return asyncio.get_event_loop().run_until_complete(read_config("wet-mcp"))
    except Exception:
        return None


def apply_config(config: dict[str, str]) -> None:
    """Apply config dict to environment variables."""
    for key, value in config.items():
        if value and key not in os.environ:
            os.environ[key] = value
            logger.debug("Applied relay config: {}", key)


async def trigger_relay_setup() -> dict[str, str] | None:
    """Manually trigger relay setup. Returns config dict or None."""
    try:
        from mcp_relay_core.relay.client import create_session, poll_for_result

        from .relay_schema import RELAY_SCHEMA

        relay_url = os.environ.get("MCP_RELAY_URL", DEFAULT_RELAY_URL)
        session = await create_session(relay_url, "wet-mcp", RELAY_SCHEMA)

        print(
            f"\nSetup: Open this URL to configure:\n{session['relay_url']}\n",
            file=sys.stderr,
            flush=True,
        )

        config = await poll_for_result(relay_url, session)

        from mcp_relay_core.storage.config_file import write_config

        await write_config("wet-mcp", config)

        return config
    except Exception as e:
        logger.warning("Relay setup failed: {}", e)
        return None
