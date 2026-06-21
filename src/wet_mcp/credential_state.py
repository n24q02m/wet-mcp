"""Non-blocking credential state management for wet-mcp.

State machine: awaiting_setup -> setup_in_progress -> (configured | local)
Reset: configured/local -> awaiting_setup (via setup tool).

In stdio mode credentials come exclusively from environment variables
(no in-process credential form); wet-mcp's basic SearXNG search works
with zero env, while tools that need upstream API keys (Jina / Gemini /
OpenAI / Cohere / GDrive) return a runtime error if their env vars are
missing. The browser-form / paste-cred flow lives only in HTTP mode --
see ``run_http_server`` in ``wet_mcp.server`` -- which is opt-in via
``--http`` / ``MCP_TRANSPORT=http`` / ``TRANSPORT_MODE=http``.

Storage: migrated from shared mcp_core.storage.config_file (config.enc) to
per-plugin mcp_core.storage.per_plugin_store.PerPluginStore so each plugin
has isolated credential files (~/.<plugin>-mcp/config.json). Multi-user HTTP
mode uses PerPluginStore("wet", sub) for per-JWT-sub isolation.
"""

from __future__ import annotations

import asyncio
import contextvars
import os
from collections.abc import Callable
from enum import Enum
from typing import Any

from loguru import logger
from mcp_core.storage.backends import backend_from_env
from mcp_core.storage.per_plugin_store import PerPluginStore

SERVER_NAME = "wet-mcp"
PLUGIN_NAME = "wet"

# Per-request JWT subject context for HTTP multi-user mode.
#
# Set by the ``auth_scope`` middleware in ``run_http_server`` AFTER mcp-core
# verifies the JWT, BEFORE the ASGI tool handler runs. Tool handlers read
# this via ``credentials_for_current_request()`` to look up the right
# per-sub PerPluginStore bucket. ``contextvars.ContextVar`` is asyncio-task
# isolated, so concurrent tool calls from different users do not bleed
# credentials across each other.
#
# Stays ``None`` in stdio / single-user HTTP mode — both fall back to
# environment variables (or the shared local PerPluginStore via the
# ``resolve_credential_state`` startup path).
_current_sub: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "wet_current_sub", default=None
)

# Grace window so the browser renders "Setup complete!" before the local spawn closes.
_SPAWN_CLEANUP_S = 5.0

CLOUD_KEYS = [
    "JINA_AI_API_KEY",
    "GEMINI_API_KEY",
    "OPENAI_API_KEY",
    "COHERE_API_KEY",
    "ANTHROPIC_API_KEY",
    "XAI_API_KEY",
]


class CredentialState(Enum):
    AWAITING_SETUP = "awaiting_setup"
    SETUP_IN_PROGRESS = "setup_in_progress"
    CONFIGURED = "configured"
    LOCAL = "local"


# Module-level state
_state = CredentialState.AWAITING_SETUP
_setup_url: str | None = None
_active_handle: Any | None = None  # LocalServerHandle
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

    def _complete_then_cleanup() -> None:
        try:
            mark_complete()
        finally:
            # GDrive finished: stop the local credential-form spawn so the
            # stdio parent process isn't holding an idle HTTP server.
            _schedule_spawn_cleanup()

    set_gdrive_complete_callback(_complete_then_cleanup)

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
    2. CONFIG FILE -- HTTP MODE ONLY -- if saved config has cloud keys,
       apply to env, state = CONFIGURED. Stdio mode skips this per spec
       2026-05-01-stdio-pure-http-multiuser.md §4.1 + OQ3 ("Stdio mode
       reads credentials from env vars ONLY"). PerPluginStore is HTTP-mode
       persistence for resilience across server restarts.
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

    # 2. Per-plugin store fallback ONLY in HTTP mode (per spec §4.1 + OQ3:
    # stdio reads env vars ONLY, PerPluginStore is HTTP-mode persistence
    # for resilience across server restarts). wet-mcp has optional creds
    # (basic SearXNG search works without env), so AWAITING_SETUP is an
    # acceptable end state for stdio mode.
    import sys

    is_http = (
        "--http" in sys.argv
        or os.environ.get("MCP_TRANSPORT") == "http"
        or os.environ.get("TRANSPORT_MODE") == "http"
    )
    if is_http:
        try:
            saved = PerPluginStore(PLUGIN_NAME, backend=backend_from_env()).load()
            if saved and any(saved.get(k) for k in CLOUD_KEYS):
                # Apply to env vars
                for key, value in saved.items():
                    if value and key not in os.environ:
                        os.environ[key] = value
                logger.info(
                    "Config loaded from per-plugin store (~/.wet-mcp/config.json)"
                )
                _state = CredentialState.CONFIGURED
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


async def _close_active_handle() -> None:
    """Best-effort close of the module-level local credential-form handle."""
    global _active_handle

    handle = _active_handle
    _active_handle = None
    if handle is None:
        return
    try:
        await handle.close()
    except Exception:
        logger.opt(exception=True).debug(
            "Best-effort close of credential-form handle failed"
        )


def _schedule_spawn_cleanup(grace_s: float = _SPAWN_CLEANUP_S) -> None:
    """Schedule detached cleanup of the local credential-form spawn."""
    if _active_handle is None:
        return

    async def _delayed_close() -> None:
        try:
            await asyncio.sleep(grace_s)
            await _close_active_handle()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.opt(exception=True).debug("Delayed spawn cleanup failed")

    try:
        task = asyncio.create_task(_delayed_close())
        task.add_done_callback(lambda _t: None)
    except RuntimeError:
        # No running loop; nothing to do -- the handle will be cleaned up on reset.
        pass


def store_for_sub(sub: str, config: dict[str, str]) -> None:
    """Persist a credential dict for a specific JWT ``sub``.

    Delegates to PerPluginStore(PLUGIN_NAME, sub) which writes to
    ~/.wet-mcp/subs/<sub>/config.json with AES-GCM encryption keyed
    from CREDENTIAL_SECRET env var.
    """
    PerPluginStore(PLUGIN_NAME, sub, backend=backend_from_env()).save(config)


def read_for_sub(sub: str) -> dict[str, str]:
    """Load the credential dict previously stored for ``sub``.

    Returns an empty dict when no credentials have been saved for the
    subject yet (first /authorize for a brand-new user).
    """
    return PerPluginStore(PLUGIN_NAME, sub, backend=backend_from_env()).load() or {}


def set_current_sub(sub: str | None) -> None:
    """Set the JWT ``sub`` for the current request (HTTP multi-user mode).

    Called by the ``auth_scope`` middleware in ``run_http_server`` so per-
    tool-call handlers can resolve credentials for the right user via
    :func:`credentials_for_current_request`. Pass ``None`` to clear.
    """
    _current_sub.set(sub)


def get_current_sub() -> str | None:
    """Return the JWT ``sub`` set by the current HTTP request, if any."""
    return _current_sub.get()


def credentials_for_current_request() -> dict[str, str]:
    """Return the credential dict applicable to the current request.

    HTTP multi-user mode: the ``auth_scope`` middleware sets ``_current_sub``
    from the verified JWT before the tool handler runs. We look up that
    user's per-sub PerPluginStore bucket and return its contents (empty
    dict if the user has not completed setup yet — caller should branch
    to AWAITING_SETUP error).

    Stdio / single-user HTTP / no-JWT contexts: ``_current_sub`` is ``None``
    and we fall back to the process environment (already populated from
    env vars or, for HTTP single-user, from PerPluginStore by
    :func:`resolve_credential_state`).
    """
    sub = _current_sub.get()
    if sub is None:
        return {k: v for k, v in os.environ.items() if k in CLOUD_KEYS and v}
    return read_for_sub(sub)


# LLM-provider key env vars, in fallback-priority order. Used by the
# sub-aware LLM availability gates (agent_orchestrator.detect_llm_provider /
# llm._has_llm_provider). GOOGLE_API_KEY is the GEMINI alias; ANTHROPIC and
# XAI round out the litellm-passthrough providers the relay form offers.
LLM_PROVIDER_KEYS = (
    "GEMINI_API_KEY",
    "GOOGLE_API_KEY",
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "XAI_API_KEY",
)


def detect_llm_provider_key() -> str | None:
    """Return the first available LLM-provider key env name, or ``None``.

    Sub-aware: in HTTP multi-user mode (``_current_sub`` set) it reads the
    request's per-sub bucket via :func:`credentials_for_current_request` so
    per-sub keys -- which never live in ``os.environ`` -- are seen. In stdio /
    single-user mode it additionally consults ``os.environ`` directly so the
    GEMINI alias ``GOOGLE_API_KEY`` (not a ``CLOUD_KEYS`` member) is still
    honored. Order is the litellm fallback priority.

    Centralises the availability check that ``agent_orchestrator`` and ``llm``
    used to hand-maintain against an ``os.getenv`` tuple that (a) omitted
    ANTHROPIC and (b) was blind to per-sub buckets.
    """
    sub = _current_sub.get()
    creds = credentials_for_current_request()
    for key in LLM_PROVIDER_KEYS:
        if creds.get(key):
            return key
        # Single-user only: also honor env vars outside CLOUD_KEYS (the
        # GOOGLE->GEMINI alias). Per-sub mode must NOT fall back to os.environ
        # (that would read another process-global value, not this user's).
        if sub is None and os.getenv(key):
            return key
    return None


def has_llm_provider() -> bool:
    """Whether any LLM provider key is available for the current request."""
    return detect_llm_provider_key() is not None


def api_key_for_model(model: str) -> str | None:
    """Resolve the provider API key for ``model`` from the CURRENT request.

    HTTP multi-user (``_current_sub`` set): return the ``<PROVIDER>_API_KEY``
    from THAT subject's per-sub bucket so the cloud dispatch (embedder /
    reranker / llm) passes it EXPLICITLY per call — instead of leaking it
    into the process-global ``os.environ``, which bled one ``sub``'s keys
    into another's request (``os.environ`` is shared mutable state, not
    contextvar-isolated).

    Single-user / stdio (no sub): return ``None`` so litellm's own provider
    env fallback applies unchanged — the single-user dispatch contract is
    untouched (this is the documented "empty api_key -> None -> env" path).
    """
    sub = _current_sub.get()
    if sub is None:
        return None
    from mcp_core.llm.providers import key_env_for_model

    key_env = key_env_for_model(model)
    if not key_env:
        return None
    return read_for_sub(sub).get(key_env) or None


def _await_backend_ready() -> None:
    """E.1: when the active backend is CF KV, poll its readiness probe before the
    first credential write so the PUT never races outbound-interception. No-op for
    LocalFs (stdio/VM) and any backend without a ``ready()`` method.
    """
    backend = backend_from_env()
    ready = getattr(backend, "ready", None)
    if callable(ready) and not ready():
        logger.warning(
            "CF KV backend not ready before credential save; "
            "relying on client retry-on-500 backstop"
        )


def poll_until_readable(sub: str | None, retries: int = 8, delay: float = 0.5) -> bool:
    """E.2: after a credential save, confirm the key is read-back-able from the
    backend before reporting setup success, closing the KV cross-colo
    eventual-consistency window (~60s) where the serving DO still sees "not
    configured". Returns True once the blob is present, False if it never
    propagates within the budget (caller proceeds; the client awaiting-setup poll
    in ``cf_full_flow.py`` is the backstop). Reads raw ciphertext (presence is the
    signal; no decrypt needed).
    """
    import time

    backend = backend_from_env()
    key = f"{PLUGIN_NAME}/subs/{sub}/config" if sub else f"{PLUGIN_NAME}/config"
    for attempt in range(retries):
        try:
            if backend.get(key) is not None:
                return True
        except Exception:
            pass  # transient read error during propagation -> keep polling
        if attempt + 1 < retries:
            time.sleep(delay)
    logger.warning(
        f"credential key {key} not yet readable after save; "
        "relying on client awaiting-setup poll backstop"
    )
    return False


def _sync_redundant_on_cf() -> bool:
    """Whether Google Drive docs-sync is redundant on this deployment.

    On Cloudflare the docs DB is D1 + Vectorize (durable across container
    recreate), so the GDrive delta-sync is redundant. Skip the device-code flow
    there so the relay never offers a non-functional Google Drive setup.
    """
    return os.environ.get("DOCS_DB_BACKEND", "").strip().lower() == "cf-d1"


def save_credentials(config: dict[str, str], context: dict[str, str]) -> dict | None:
    """Save credentials from OAuth form to ``config.json`` and apply to environment.

    ``context`` carries the per-authorize ``sub`` issued by mcp-core's local
    OAuth AS. In remote multi-user mode (``PUBLIC_URL`` set) we route the
    credentials into a per-sub bucket via :func:`store_for_sub` so concurrent
    users do not overwrite each other. In single-user mode the subject is
    ignored and a single ``~/.wet-mcp/config.json`` on the host is reused.

    Called by the local OAuth AS when the user submits API keys via the
    browser form. Writes to encrypted config file, applies to env vars
    for immediate use, re-initializes providers, and shares keys with
    sibling MCP servers.

    Returns optional dict with next_step info (e.g., GDrive device code)
    for the form to display.
    """
    global _state

    # E.1: gate the first KV PUT on outbound-interception readiness (no-op for
    # LocalFs / any backend without ready()). One probe per setup submit, at the
    # single chokepoint both branches pass through.
    _await_backend_ready()

    # Remote multi-user branch: scope credential storage by JWT sub so
    # concurrent /authorize sessions do not clobber each other. The GDrive
    # device-code flow ALSO needs to be per-sub: token lands in
    # ``~/.wet-mcp/subs/<sub>/tokens/google_drive.json`` so user A's
    # refresh-token is invisible to user B sharing the same deployment.
    if os.environ.get("PUBLIC_URL"):
        sub = context.get("sub") if context else None
        if not sub:
            raise RuntimeError("multi-user mode: SubjectContext sub required")
        store_for_sub(sub, config)
        poll_until_readable(sub)  # E.2: confirm propagation before reporting success
        _state = CredentialState.CONFIGURED
        logger.info(f"Credentials saved for sub={sub} via remote multi-user form")

        # Mirror the single-user GDrive trigger but pin token storage to
        # this sub. Without this branch, multi-user mode silently skipped
        # GDrive auth entirely (cross-user token leak gap, spec 04-25 #134).
        try:
            from wet_mcp.config import settings as s

            if (
                s.google_drive_client_id
                and s.google_drive_client_secret
                and not _sync_redundant_on_cf()
            ):
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
                        "GDrive device code (sub={}), user_code={}",
                        sub,
                        device_data.get("user_code"),
                    )
                    import asyncio
                    import threading

                    def _poll() -> None:
                        asyncio.run(
                            _gdrive_token_poll(
                                s.google_drive_client_id,
                                s.google_drive_client_secret,
                                device_data["device_code"],
                                device_data.get("interval", 5),
                                device_data.get("expires_in", 1800),
                                sub=sub,
                            )
                        )

                    threading.Thread(target=_poll, daemon=True).start()
                    return {
                        "type": "oauth_device_code",
                        "verification_url": device_data["verification_url"],
                        "user_code": device_data["user_code"],
                    }
        except Exception:
            logger.opt(exception=True).debug(
                "Multi-user GDrive device code request failed (non-fatal)"
            )
        return None

    from wet_mcp.relay_setup import apply_config

    # Persist to per-plugin store (~/.wet-mcp/config.json)
    PerPluginStore(PLUGIN_NAME, backend=backend_from_env()).save(config)
    poll_until_readable(None)  # E.2: confirm propagation before reporting success

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

    # Trigger GDrive OAuth Device Code flow if configured
    try:
        from wet_mcp.config import settings as s

        if (
            s.google_drive_client_id
            and s.google_drive_client_secret
            and not _sync_redundant_on_cf()
        ):
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

    # No GDrive: cloud-only setup is done -- schedule local spawn cleanup so
    # the browser renders "Setup complete!" then the local server closes.
    _schedule_spawn_cleanup()
    return None


async def _gdrive_token_poll(
    client_id: str,
    client_secret: str,
    device_code: str,
    interval: int,
    expires_in: int,
    sub: str | None = None,
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
                    # Save token. In multi-user remote mode (``sub`` is
                    # set), use the per-sub bucket so concurrent users
                    # do not share a single GDrive refresh-token.
                    from wet_mcp.token_store import save_token, save_token_for_sub

                    try:
                        if sub:
                            save_token_for_sub(sub, "google_drive", data)
                        else:
                            save_token("google_drive", data)
                        logger.info("GDrive OAuth token saved successfully")
                    except Exception as exc:
                        logger.opt(exception=True).warning(
                            "GDrive token save FAILED after successful exchange: {}. "
                            "Token lost; device_code cannot be re-exchanged. "
                            "User must restart setup.",
                            exc,
                        )
                        _notify_failed(f"save_token failed: {exc}")
                        return
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

    # Close any active local credential-form spawn; fire-and-forget so callers
    # don't need to be async.
    if _active_handle is not None:
        try:
            task = asyncio.create_task(_close_active_handle())
            task.add_done_callback(lambda _t: None)
        except RuntimeError:
            pass

    try:
        from mcp_core import clear_mode

        clear_mode(SERVER_NAME)
        PerPluginStore(PLUGIN_NAME, backend=backend_from_env()).clear()
    except Exception:
        logger.opt(exception=True).warning("Reset state failed")


def _reset_callbacks_for_test() -> None:
    """Test helper: clear callbacks so tests start from a known state.

    Not exported from the public API; tests import it directly.
    """
    global _on_gdrive_complete, _on_gdrive_failed
    _on_gdrive_complete = None
    _on_gdrive_failed = None
