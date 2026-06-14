"""Local token storage for OAuth tokens.

Stores tokens in ~/.wet-mcp/tokens/<provider>.json with secure
file permissions (0600). Eliminates the need to paste long tokens
into MCP config -- tokens are persisted locally after the
first interactive OAuth flow.

Token lifecycle:
1. First run: no token -> Device Code OAuth flow -> token saved
2. Subsequent runs: token loaded from disk -> auto-refreshed when expired
3. Re-auth: delete token file -> next run triggers new OAuth flow
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from mcp_core.storage.per_plugin_store import PerPluginStore

from wet_mcp.config import settings
from wet_mcp.credential_state import PLUGIN_NAME  # "wet"


def _token_store(provider: str, sub: str | None, backend) -> PerPluginStore:
    from mcp_core.storage.backends import backend_from_env
    from mcp_core.storage.per_plugin_store import PerPluginStore

    return PerPluginStore(
        PLUGIN_NAME,
        sub,
        backend=backend or backend_from_env(),
        sub_key=f"tokens/{provider}",
    )


def _validate_safe_name(name: str) -> None:
    """Validate that a name does not contain path separators or traversal sequences."""
    if not name:
        raise ValueError("Name cannot be empty")
    if "/" in name or "\\" in name or ".." in name:
        raise ValueError(f"Invalid path component: {name}")


def _get_token_dir() -> Path:
    """Get directory for token storage (~/.wet-mcp/tokens/).

    Single-user (default) layout. Multi-user remote mode uses
    :func:`_get_token_dir_for_sub` instead so concurrent JWT subjects
    do not share GDrive tokens.
    """
    return settings.get_data_dir() / "tokens"


def get_token_path(provider: str) -> Path:
    """Return the secure file path for a provider token."""
    _validate_safe_name(provider)
    return _get_token_dir() / f"{provider}.json"


def _get_token_dir_for_sub(sub: str) -> Path:
    """Per-sub token directory (``~/.wet-mcp/subs/<sub>/tokens``).

    Multi-user remote mode (``PUBLIC_URL`` set) keys every artifact by
    JWT ``sub`` so user A's GDrive refresh-token is not visible to
    user B sharing the same wet-mcp deployment.
    """
    _validate_safe_name(sub)
    return settings.get_data_dir() / "subs" / sub / "tokens"


def get_token_path_for_sub(sub: str, provider: str) -> Path:
    """Get path for a provider's token file scoped to a specific JWT sub."""
    _validate_safe_name(sub)
    _validate_safe_name(provider)
    return _get_token_dir_for_sub(sub) / f"{provider}.json"


def load_token(provider: str, backend=None) -> dict | None:
    """Load stored OAuth token for a provider (decrypted via PerPluginStore)."""
    _validate_safe_name(provider)
    try:
        data = _token_store(provider, None, backend).load()
    except Exception as e:  # corrupt blob / wrong key -> absent (triggers re-auth)
        logger.warning(f"Failed to load token for {provider}: {e}")
        return None
    if isinstance(data, dict) and "access_token" in data:
        return data
    return None


def save_token(provider: str, token: dict, backend=None) -> None:
    """Save OAuth token, encrypted via PerPluginStore + selected backend."""
    _validate_safe_name(provider)
    _token_store(provider, None, backend).save(token)
    logger.info(f"Token saved (encrypted): wet/tokens/{provider}")


def save_token_for_sub(sub: str, provider: str, token: dict, backend=None) -> None:
    """Save a per-JWT-sub OAuth token, encrypted via PerPluginStore."""
    _validate_safe_name(sub)
    _validate_safe_name(provider)
    _token_store(provider, sub, backend).save(token)
    logger.info(f"Token saved (encrypted, sub={sub}): wet/subs/{sub}/tokens/{provider}")


def load_token_for_sub(sub: str, provider: str, backend=None) -> dict | None:
    """Load a per-JWT-sub OAuth token. None when absent/undecryptable."""
    _validate_safe_name(sub)
    _validate_safe_name(provider)
    try:
        data = _token_store(provider, sub, backend).load()
    except Exception as e:
        logger.warning(f"Failed to load token for sub={sub} provider={provider}: {e}")
        return None
    if isinstance(data, dict) and "access_token" in data:
        return data
    return None


# Spec naming alias: the HTTP multi-user wiring spec
# (``2026-05-01-stdio-pure-http-multiuser.md``) refers to ``read_token_for_sub``
# as the mirror of ``save_token_for_sub``. Keep both names available so
# call sites can use whichever reads more clearly in context.
read_token_for_sub = load_token_for_sub
