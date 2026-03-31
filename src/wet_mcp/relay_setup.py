"""Credential resolution for wet-mcp.

Resolution order (relay only when ALL local sources are empty):
1. ENV VARS          -- User explicitly set (highest priority, skip everything)
2. RELAY CONFIG      -- Saved from previous relay setup (~/.config/mcp/config.enc)
3. RELAY SETUP       -- Interactive, ONLY when steps 1-2 are ALL empty (120s timeout)
4. LOCAL MODE        -- Fallback (ONNX embedding, SearXNG search)
"""

from __future__ import annotations

import os
import sys

from loguru import logger

DEFAULT_RELAY_URL = "https://wet-mcp.n24q02m.com"
SERVER_NAME = "wet-mcp"

CLOUD_KEYS = [
    "JINA_AI_API_KEY",
    "GEMINI_API_KEY",
    "OPENAI_API_KEY",
    "COHERE_API_KEY",
]

# Shorter timeout for optional-credential servers (user can skip)
RELAY_TIMEOUT_S = 120.0


def load_config_from_file() -> dict[str, str] | None:
    """Try to load config from encrypted config file. Returns None if not found."""
    try:
        from mcp_relay_core.storage.config_file import read_config

        saved = read_config(SERVER_NAME)
        if saved and any(saved.get(k) for k in CLOUD_KEYS):
            logger.info("Config loaded from file")
            return saved
        return None
    except Exception:
        return None


def apply_config(config: dict[str, str]) -> None:
    """Apply config dict to environment variables."""
    for key, value in config.items():
        if value and key not in os.environ:
            os.environ[key] = value
            logger.debug("Applied relay config: {}", key)


async def ensure_config() -> dict[str, str] | None:
    """Resolve config: env vars -> config file -> relay setup -> local fallback.

    Relay is ONLY triggered when steps 1-2 are ALL empty.
    Uses 120s timeout since wet-mcp works locally without credentials.

    Returns:
        Config dict with API keys, or None if skipped/failed (local mode).
    """
    # 1. Check if env vars already provide cloud keys (highest priority)
    if any(os.environ.get(k) for k in CLOUD_KEYS):
        logger.info("Cloud API keys found in environment, skipping relay")
        return None  # env vars take priority, no relay needed

    # 2. Check saved relay config file
    config = load_config_from_file()
    if config is not None:
        apply_config(config)
        return config

    # 3. No local credentials found -- trigger relay setup
    logger.info("No cloud credentials found. Starting relay setup...")
    try:
        from mcp_relay_core.relay.client import create_session, poll_for_result

        from .relay_schema import RELAY_SCHEMA

        relay_url = os.environ.get("MCP_RELAY_URL", DEFAULT_RELAY_URL)
        session = await create_session(relay_url, SERVER_NAME, RELAY_SCHEMA)  # ty: ignore[invalid-argument-type]

        print(
            f"\nConfigure cloud providers (optional, 120s timeout):"
            f"\n{session.relay_url}"
            f"\nSkip to use local mode (ONNX embedding + SearXNG).\n",
            file=sys.stderr,
            flush=True,
        )

        config = await poll_for_result(relay_url, session, timeout_s=RELAY_TIMEOUT_S)

        # Save to config file for future use
        from mcp_relay_core.storage.config_file import write_config

        write_config(SERVER_NAME, config)
        logger.info("Config saved successfully")

        # Notify relay page that setup is complete
        try:
            import httpx

            async with httpx.AsyncClient() as http:
                await http.post(
                    f"{relay_url}/api/sessions/{session.session_id}/messages",
                    json={
                        "type": "complete",
                        "text": "wet-mcp config saved. Setup complete!",
                    },
                )
        except Exception:
            pass

        apply_config(config)
        return config

    except RuntimeError as e:
        if "RELAY_SKIPPED" in str(e):
            logger.info("Relay setup skipped by user. Using local mode.")
        elif "timed out" in str(e).lower():
            logger.info("Relay setup timed out. Using local mode.")
        else:
            logger.debug("Relay setup ended: {}", e)
        return None
    except Exception as e:
        logger.debug("Relay setup unavailable: {}. Using local mode.", e)
        return None


async def trigger_relay_setup() -> dict[str, str] | None:
    """Manually trigger relay setup (from MCP setup tool). No timeout limit."""
    try:
        from mcp_relay_core.relay.client import create_session, poll_for_result

        from .relay_schema import RELAY_SCHEMA

        relay_url = os.environ.get("MCP_RELAY_URL", DEFAULT_RELAY_URL)
        session = await create_session(relay_url, SERVER_NAME, RELAY_SCHEMA)  # ty: ignore[invalid-argument-type]

        session_url: str = session.relay_url
        print(
            f"\nSetup: Open this URL to configure:\n{session_url}\n",
            file=sys.stderr,
            flush=True,
        )

        config = await poll_for_result(relay_url, session)

        from mcp_relay_core.storage.config_file import write_config

        write_config(SERVER_NAME, config)

        # Notify relay page that setup is complete
        try:
            import httpx

            async with httpx.AsyncClient() as http:
                await http.post(
                    f"{relay_url}/api/sessions/{session.session_id}/messages",
                    json={
                        "type": "complete",
                        "text": "wet-mcp config saved. Setup complete!",
                    },
                )
        except Exception:
            pass

        return config

    except RuntimeError as e:
        if "RELAY_SKIPPED" in str(e):
            logger.info("Relay setup skipped by user")
            return None
        logger.warning("Relay setup failed: {}", e)
        return None
    except Exception as e:
        logger.warning("Relay setup failed: {}", e)
        return None
