"""Credential resolution for wet-mcp.

Resolution order (relay only when ALL local sources are empty):
1. ENV VARS          -- User explicitly set (highest priority, skip everything)
2. RELAY CONFIG      -- Saved from previous relay setup (~/.wet-mcp/config.json)
3. RELAY SETUP       -- Interactive, ONLY when steps 1-2 are ALL empty (120s timeout)
4. LOCAL MODE        -- Fallback (ONNX embedding, SearXNG search)

Storage: migrated from mcp_core.storage.config_file (shared config.enc) to
mcp_core.storage.per_plugin_store.PerPluginStore("wet") for per-plugin isolation.
"""

from __future__ import annotations

import os
import sys

from loguru import logger
from mcp_core.storage.per_plugin_store import PerPluginStore

SERVER_NAME = "wet-mcp"
PLUGIN_NAME = "wet"

CLOUD_KEYS = [
    "JINA_AI_API_KEY",
    "GEMINI_API_KEY",
    "OPENAI_API_KEY",
    "COHERE_API_KEY",
]

# 5 minutes: user needs time to copy URL, open browser, fill 4 keys
RELAY_TIMEOUT_S = 300.0


def load_config_from_file() -> dict[str, str] | None:
    """Try to load config from per-plugin store. Returns None if not found.

    Name kept for backward compatibility; storage has migrated from
    shared config.enc to ~/.wet-mcp/config.json via PerPluginStore.
    """
    try:
        saved = PerPluginStore(PLUGIN_NAME).load()
        if saved and any(saved.get(k) for k in CLOUD_KEYS):
            logger.info("Config loaded from per-plugin store (~/.wet-mcp/config.json)")
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


async def ensure_config(
    *, force: bool = False, timeout: float | None = RELAY_TIMEOUT_S
) -> dict[str, str] | None:
    """Resolve config: env vars -> config file -> relay setup -> local fallback.

    Args:
        force: Skip env-var and config-file checks, go straight to relay.
        timeout: Relay poll timeout in seconds. None = no timeout (manual setup).

    Relay is ONLY triggered when steps 1-2 are ALL empty (unless ``force=True``).

    Returns:
        Config dict with API keys, or None if skipped/failed (local mode).
    """
    if not force:
        # 1. Check if env vars already provide cloud keys (highest priority)
        if any(os.environ.get(k) for k in CLOUD_KEYS):
            logger.info("Cloud API keys found in environment, skipping relay")
            return None  # env vars take priority, no relay needed

        # 2. Check saved relay config file
        config = load_config_from_file()
        if config is not None:
            apply_config(config)
            return config

    # 3. No local credentials found (or forced) -- trigger relay setup.
    # Per mode-matrix 2.5, wet-mcp default is `http local relay`; `remote-relay`
    # mode requires user-supplied URL (no centralized wet-mcp.n24q02m.com).
    # Surface the misconfiguration as a hard failure BEFORE the broad try/except
    # so the caller (run_remote_relay -> main) propagates it rather than silently
    # falling back to local mode.
    relay_url = os.environ.get("MCP_RELAY_URL")
    if not relay_url:
        raise RuntimeError(
            "MCP_RELAY_URL env var is required for remote-relay mode. "
            "wet-mcp default mode is 'http local relay' (no remote URL needed). "
            "For self-host remote-relay, set MCP_RELAY_URL=https://<your-instance>."
        )

    logger.info("Starting relay setup...")
    try:
        return await _run_relay_setup(relay_url, timeout)
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


async def _run_relay_setup(relay_url: str, timeout: float | None) -> dict[str, str]:
    """Perform the interactive relay setup flow."""
    from mcp_core.relay.client import create_session, poll_for_result

    from .relay_schema import RELAY_SCHEMA

    session = await create_session(relay_url, SERVER_NAME, RELAY_SCHEMA)  # ty: ignore[invalid-argument-type]

    timeout_msg = f", {int(timeout)}s timeout" if timeout else ""
    print(
        f"\nConfigure cloud providers (optional{timeout_msg}):"
        f"\n{session.relay_url}"
        f"\nSkip to use local mode (ONNX embedding + SearXNG).\n",
        file=sys.stderr,
        flush=True,
    )

    config = await poll_for_result(relay_url, session, timeout_s=timeout)  # ty: ignore[invalid-argument-type]

    # Save to per-plugin store for future use (~/.wet-mcp/config.json)
    PerPluginStore(PLUGIN_NAME).save(config)
    logger.info("Config saved successfully")

    apply_config(config)

    # Notify relay page: config saved
    await _notify_relay_status(
        relay_url,
        session.session_id,
        "info",
        "API keys saved. Starting Google Drive sync setup...",
    )

    # Trigger GDrive OAuth Device Code
    gdrive_ok = await _setup_google_drive(relay_url, session.session_id)

    # Send complete message
    msg = (
        "Setup complete!"
        if gdrive_ok
        else "API keys saved. Google Drive sync can be configured later via config tool."
    )
    await _notify_relay_status(relay_url, session.session_id, "complete", msg)

    return config


async def _notify_relay_status(
    relay_url: str, session_id: str, message_type: str, text: str
) -> None:
    """Send a status message to the relay session."""
    try:
        import httpx

        async with httpx.AsyncClient() as http:
            await http.post(
                f"{relay_url}/api/sessions/{session_id}/messages",
                json={"type": message_type, "text": text},
            )
    except Exception:
        pass


async def _setup_google_drive(relay_url: str, session_id: str) -> bool:
    """Trigger Google Drive OAuth Device Code flow if configured."""
    from wet_mcp.config import settings as _settings

    if not _settings.google_drive_client_id:
        return False

    logger.info("Starting Google Drive OAuth setup...")
    try:
        from wet_mcp.sync import setup_google_auth

        return await setup_google_auth(
            relay_url=relay_url,
            session_id=session_id,
        )
    except Exception as e:
        logger.warning(f"GDrive OAuth setup failed: {e}")
        return False
