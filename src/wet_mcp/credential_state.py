"""Non-blocking credential state management for wet-mcp.

State machine: awaiting_setup -> setup_in_progress -> (configured | local)
Reset: configured/local -> awaiting_setup (via setup tool)
"""

from __future__ import annotations

import os
from collections.abc import Callable
from enum import Enum

from loguru import logger

SERVER_NAME = "wet-mcp"

CLOUD_KEYS = [
    "JINA_AI_API_KEY",
    "GEMINI_API_KEY",
    "OPENAI_API_KEY",
    "COHERE_API_KEY",
]


class CredentialState(Enum):
    AWAITING_SETUP = "awaiting_setup"
    SETUP_IN_PROGRESS = "setup_in_progress"
    CONFIGURED = "configured"
    LOCAL = "local"


# Module-level state
_state = CredentialState.AWAITING_SETUP
_setup_url: str | None = None
_on_gdrive_complete: Callable[[], None] | None = None
# Failure callback signature matches mcp-core's mark_setup_failed: optional
# key + error message. Wired by the HTTP server so the browser's
# /setup-status poll receives ``error:<message>`` instead of spinning forever
# when Google rejects the device code (invalid_grant / expired_token / etc.).
_on_gdrive_failed: Callable[[str, str], None] | None = None


def set_gdrive_complete_callback(cb: Callable[[], None]) -> None:
    """Set callback for when GDrive OAuth completes (used by HTTP server)."""
    global _on_gdrive_complete
    _on_gdrive_complete = cb
    logger.debug("GDrive complete callback registered")


def set_gdrive_failed_callback(cb: Callable[[str, str], None]) -> None:
    """Set callback for when GDrive OAuth fails upstream (used by HTTP server).

    The callback receives ``(key, error_message)`` matching the
    ``mark_setup_failed(key, error)`` signature exposed by mcp-core's local
    OAuth app. It is invoked by ``_gdrive_token_poll`` whenever Google
    returns a terminal error (``invalid_grant``, ``expired_token``,
    ``access_denied``, etc.) so the browser's ``/setup-status`` poll
    surfaces the error and stops waiting.
    """
    global _on_gdrive_failed
    _on_gdrive_failed = cb
    logger.debug("GDrive failed callback registered")


def wire_gdrive_callbacks(
    mark_complete: Callable[[], None],
    mark_failed: Callable[..., None] | None = None,
) -> None:
    """Wire GDrive completion + optional failure callbacks in one call.

    Intended for use as ``setup_complete_hook``. mcp-core detects the hook
    signature by arity:

    - Older mcp-core (<1.3.0) passes 1 positional arg: ``hook(mark_complete)``.
      ``mark_failed`` stays ``None`` and GDrive terminal errors go
      server-log-only (legacy behavior).
    - Newer mcp-core (>=1.3.0) passes 2 args: ``hook(mark_complete, mark_failed)``.
      ``mark_failed`` wires through ``mark_setup_failed`` so the browser
      form stops spinning and shows the error.

    Making ``mark_failed`` optional here means wet-mcp stays forward-compatible
    with both versions; no lock-step release required between wet-mcp and
    mcp-core.
    """
    set_gdrive_complete_callback(mark_complete)

    global _on_gdrive_failed

    if mark_failed is None:
        _on_gdrive_failed = None
        logger.debug("GDrive complete callback wired (1-arg legacy core)")
        return

    def _cb(_key: str, error: str) -> None:
        # mcp-core's mark_setup_failed(key, error) expects the key positionally.
        # We always operate on "gdrive" so hardcode it here.
        try:
            mark_failed("gdrive", error)
        except Exception:
            logger.opt(exception=True).debug("mark_setup_failed call failed")

    _on_gdrive_failed = _cb
    logger.debug("GDrive complete + failed callbacks wired (2-arg)")


def get_state() -> CredentialState:
    """Return current credential state."""
    return _state


def get_setup_url() -> str | None:
    """Return current relay setup URL (if any)."""
    return _setup_url


def resolve_credential_state() -> CredentialState:
    """Fast, synchronous credential check. Called during lifespan startup.

    Checks (in order):
    1. ENV VARS -- if any CLOUD_KEYS present, state = CONFIGURED
    2. CONFIG FILE -- if saved config has cloud keys, apply to env, state = CONFIGURED
    3. LOCAL MODE MARKER -- if user explicitly skipped, state = LOCAL
    4. NOTHING -- state = AWAITING_SETUP (server starts fast, relay triggered lazily)

    Returns new state. Takes <10ms.
    """
    global _state

    # 1. Check env vars
    if any(os.environ.get(k) for k in CLOUD_KEYS):
        logger.info("Cloud API keys found in environment")
        _state = CredentialState.CONFIGURED
        return _state

    # 2. Check config file
    try:
        from mcp_core.storage.config_file import read_config

        saved = read_config(SERVER_NAME)
        if saved and any(saved.get(k) for k in CLOUD_KEYS):
            # Apply to env vars
            for key, value in saved.items():
                if value and key not in os.environ:
                    os.environ[key] = value
            logger.info("Config loaded from encrypted file")
            _state = CredentialState.CONFIGURED
            # Propagate shared cloud keys to sibling servers on every startup
            _share_cloud_keys_to_peers(saved)
            return _state
    except Exception:
        logger.opt(exception=True).debug("Failed to read config")

    # 3. Check local mode marker
    try:
        from mcp_core import get_mode

        mode = get_mode(SERVER_NAME)
        if mode == "local":
            logger.info("Local mode marker found, skipping relay")
            _state = CredentialState.LOCAL
            return _state
    except Exception:
        logger.opt(exception=True).debug("Failed to get mode")

    # 4. Nothing found
    logger.info("No credentials found -- server starting in awaiting_setup mode")
    _state = CredentialState.AWAITING_SETUP
    return _state


async def trigger_relay_setup(
    *, force: bool = False, timeout: float | None = None
) -> str | None:
    """Start relay session (lazy trigger). Returns setup URL or None.

    Uses SessionLock to reuse existing sessions across parallel processes.
    Tries to open browser automatically.
    Does NOT block -- returns URL immediately for the tool to include in response.
    """
    global _state, _setup_url

    if not force and _state not in (CredentialState.AWAITING_SETUP,):
        return _setup_url

    _state = CredentialState.SETUP_IN_PROGRESS

    try:
        # Check for existing session via lock
        from mcp_core import acquire_session_lock

        existing = await acquire_session_lock(SERVER_NAME)
        if existing:
            _setup_url = existing.relay_url
            logger.info("Reusing existing relay session")
            return _setup_url

        # Create new session
        from mcp_core.relay.client import create_session

        from wet_mcp.relay_schema import RELAY_SCHEMA

        relay_base = os.environ.get("MCP_RELAY_URL", "https://wet-mcp.n24q02m.com")
        session = await create_session(relay_base, SERVER_NAME, RELAY_SCHEMA)  # ty: ignore[invalid-argument-type]

        # Save session lock for parallel processes
        import time

        from mcp_core import SessionInfo, write_session_lock

        await write_session_lock(
            SERVER_NAME,
            SessionInfo(
                session_id=session.session_id,
                relay_url=session.relay_url,
                created_at=time.time(),
            ),
        )

        _setup_url = session.relay_url

        # Try to open browser (best-effort)
        from mcp_core import try_open_browser

        try_open_browser(session.relay_url)

        logger.info("Relay session created: {}", session.relay_url)

        # Start background poll task (non-blocking)
        import asyncio

        asyncio.create_task(_poll_relay_background(relay_base, session, timeout))

        return _setup_url

    except Exception as e:
        logger.debug("Relay setup failed: {}. Server continues in awaiting_setup.", e)
        _state = CredentialState.AWAITING_SETUP
        return None


async def _poll_relay_background(
    relay_base: str, session: object, timeout: float | None
) -> None:
    """Background task that polls relay and applies config when user submits."""
    global _state
    try:
        from mcp_core.relay.client import poll_for_result
        from mcp_core.storage.config_file import write_config

        poll_timeout = timeout if timeout is not None else 300.0
        config = await poll_for_result(relay_base, session, timeout_s=poll_timeout)  # ty: ignore[invalid-argument-type]

        # Save config
        write_config(SERVER_NAME, config)

        # Apply to env
        for key, value in config.items():
            if value and key not in os.environ:
                os.environ[key] = value

        _state = CredentialState.CONFIGURED
        logger.info("Relay config applied successfully")

        # Re-init providers
        from wet_mcp.config import settings

        settings.setup_providers()

        # Share cloud keys with mnemo-mcp and CRG (same keys, avoid separate relay)
        _share_cloud_keys_to_peers(config)

        # Google Drive OAuth via relay messaging (best-effort)
        session_id = getattr(session, "session_id", None)
        if session_id:
            try:
                from wet_mcp.sync import setup_google_auth

                await setup_google_auth(relay_url=relay_base, session_id=session_id)
            except Exception:
                logger.opt(exception=True).debug(
                    "GDrive OAuth via relay failed (non-fatal)"
                )

        # Notify browser: setup complete
        if session_id:
            try:
                from mcp_core.relay.client import send_message

                await send_message(
                    relay_base,
                    session_id,
                    {
                        "type": "complete",
                        "text": "Setup complete! API keys configured. You can close this tab.",
                    },
                )
            except Exception:
                logger.opt(exception=True).debug("Failed to send completion message")

        # Release session lock
        from mcp_core import release_session_lock

        await release_session_lock(SERVER_NAME)

    except RuntimeError as ex:
        if "RELAY_SKIPPED" in str(ex):
            _state = CredentialState.LOCAL
            try:
                from mcp_core import set_local_mode

                set_local_mode(SERVER_NAME)
            except Exception:
                logger.opt(exception=True).warning("Failed to set local mode")
        else:
            _state = CredentialState.AWAITING_SETUP
    except Exception:
        logger.exception("Relay polling failed")
        _state = CredentialState.AWAITING_SETUP


def _share_cloud_keys_to_peers(config: dict[str, str]) -> None:
    """Write shared cloud API keys to mnemo-mcp and CRG config files.

    wet-mcp, mnemo-mcp, and better-code-review-graph all use the same
    cloud embedding/LLM keys. Sharing avoids needing separate relay sessions
    for each server — one relay configures all three.
    """
    try:
        from mcp_core.storage.config_file import write_config

        shared = {k: v for k, v in config.items() if k in CLOUD_KEYS and v}
        if not shared:
            return
        for peer in ("mnemo-mcp", "better-code-review-graph"):
            try:
                write_config(peer, shared)
                logger.debug("Shared cloud keys to {}", peer)
            except Exception:
                logger.opt(exception=True).debug("Failed to share keys to {}", peer)
    except Exception:
        logger.opt(exception=True).debug(
            "_share_cloud_keys_to_peers failed (non-fatal)"
        )


def save_credentials(config: dict[str, str]) -> dict | None:
    """Save credentials from OAuth form to config.enc and apply to environment.

    Called by the local OAuth AS when the user submits API keys via the
    browser form. Writes to encrypted config file, applies to env vars
    for immediate use, re-initializes providers, and shares keys with
    sibling MCP servers.

    Returns optional dict with next_step info (e.g., GDrive device code)
    for the form to display.
    """
    global _state

    from mcp_core.storage.config_file import write_config

    from wet_mcp.relay_setup import apply_config

    # Persist to encrypted config file
    write_config(SERVER_NAME, config)

    # Apply to environment for immediate use
    apply_config(config)

    # Update state
    _state = CredentialState.CONFIGURED
    logger.info("Credentials saved via local OAuth form")

    # Re-init providers so new keys take effect immediately
    try:
        from wet_mcp.config import settings

        settings.setup_providers()
    except Exception:
        logger.opt(exception=True).debug(
            "Provider re-init after save failed (non-fatal)"
        )

    # Share cloud keys with sibling servers
    _share_cloud_keys_to_peers(config)

    # Trigger GDrive OAuth Device Code flow if configured
    try:
        from wet_mcp.config import settings as s

        if s.google_drive_client_id and s.google_drive_client_secret:
            import httpx

            response = httpx.post(
                "https://oauth2.googleapis.com/device/code",
                data={
                    "client_id": s.google_drive_client_id,
                    "scope": "https://www.googleapis.com/auth/drive.file",
                },
                timeout=15.0,
            )
            if response.status_code == 200:
                device_data = response.json()
                logger.info(
                    "GDrive device code requested, user_code={}",
                    device_data.get("user_code"),
                )

                # Start background polling for token
                import asyncio
                import threading

                def _poll_gdrive_token():
                    asyncio.run(
                        _gdrive_token_poll(
                            s.google_drive_client_id,
                            s.google_drive_client_secret,
                            device_data["device_code"],
                            device_data.get("interval", 5),
                            device_data.get("expires_in", 1800),
                        )
                    )

                threading.Thread(target=_poll_gdrive_token, daemon=True).start()

                # Auto-launch the default browser at Google's device-code page.
                # Best-effort -- headless hosts silently no-op and the user
                # still sees the URL rendered in the credential form.
                from mcp_core import try_open_browser

                try_open_browser(device_data["verification_url"])

                return {
                    "type": "oauth_device_code",
                    "verification_url": device_data["verification_url"],
                    "user_code": device_data["user_code"],
                }
    except Exception:
        logger.opt(exception=True).debug(
            "GDrive device code request failed (non-fatal)"
        )

    return None


async def _gdrive_token_poll(
    client_id: str,
    client_secret: str,
    device_code: str,
    interval: int,
    expires_in: int,
) -> None:
    """Background poll Google OAuth for device code token completion.

    Terminal outcomes:
    * ``access_token`` in response  -> save token + fire complete callback.
    * ``authorization_pending``     -> keep polling (user hasn't approved yet).
    * ``slow_down``                 -> increase interval + keep polling.
    * Any other ``error`` value (``invalid_grant``, ``expired_token``,
      ``access_denied``, etc.) -> fire failure callback with the error
      string and stop. The failure callback wires into mcp-core's
      ``/setup-status`` so the browser shows the message instead of
      waiting forever.
    * Loop exits via ``deadline`` without success -> fire failure callback
      with ``expired`` so the browser surfaces the timeout.
    """
    import asyncio
    import time

    import httpx

    def _notify_failed(error: str) -> None:
        if _on_gdrive_failed is None:
            return
        try:
            _on_gdrive_failed("gdrive", error)
        except Exception:
            logger.opt(exception=True).debug("GDrive failed callback raised")

    deadline = time.time() + expires_in
    async with httpx.AsyncClient() as client:
        while time.time() < deadline:
            await asyncio.sleep(interval)
            try:
                resp = await client.post(
                    "https://oauth2.googleapis.com/token",
                    data={
                        "client_id": client_id,
                        "client_secret": client_secret,
                        "device_code": device_code,
                        "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                    },
                    timeout=15.0,
                )
                data = resp.json()
                if "access_token" in data:
                    # Save token
                    from wet_mcp.token_store import save_token

                    save_token("google_drive", data)
                    logger.info("GDrive OAuth token saved successfully")
                    logger.info(
                        "GDrive authorized. Sync will start on next server restart."
                    )
                    if _on_gdrive_complete:
                        try:
                            _on_gdrive_complete()
                        except Exception:
                            logger.opt(exception=True).debug(
                                "GDrive complete callback failed"
                            )
                    return
                err = data.get("error")
                if err == "authorization_pending":
                    continue
                if err == "slow_down":
                    interval += 5
                    continue
                # Any other error from Google is terminal -- stop polling AND
                # tell the browser so the spinner stops.
                err_desc = data.get("error_description") or err or "unknown"
                logger.warning(
                    "GDrive token poll terminal error: {} ({})",
                    err,
                    err_desc,
                )
                _notify_failed(str(err_desc))
                return
            except Exception:
                logger.opt(exception=True).debug("GDrive token poll request failed")
        # Deadline exceeded without success -> surface timeout.
        logger.warning("GDrive device code flow expired before user approved")
        _notify_failed("expired")


def set_state(state: CredentialState) -> None:
    """For testing and setup tool actions."""
    global _state
    _state = state


def reset_state() -> None:
    """Reset to awaiting_setup (used by setup reset action)."""
    global _state, _setup_url
    _state = CredentialState.AWAITING_SETUP
    _setup_url = None
    try:
        from mcp_core import clear_mode
        from mcp_core.storage.config_file import delete_config

        clear_mode(SERVER_NAME)
        delete_config(SERVER_NAME)
    except Exception:
        logger.opt(exception=True).warning("Reset state failed")


def _reset_callbacks_for_test() -> None:
    """Test helper: clear callbacks so tests start from a known state.

    Not exported from the public API; tests import it directly.
    """
    global _on_gdrive_complete, _on_gdrive_failed
    _on_gdrive_complete = None
    _on_gdrive_failed = None
