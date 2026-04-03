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

import json
import os
import stat
from pathlib import Path

from loguru import logger

from wet_mcp.config import settings


def _get_token_dir() -> Path:
    """Get directory for token storage (~/.wet-mcp/tokens/)."""
    return settings.get_data_dir() / "tokens"


def get_token_path(provider: str) -> Path:
    """Get path for a provider's token file."""
    return _get_token_dir() / f"{provider}.json"


def load_token(provider: str) -> dict | None:
    """Load stored OAuth token for a provider.

    Returns the token dict, or None if not found/invalid.
    """
    path = get_token_path(provider)
    try:
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict) and "access_token" in data:
            return data
        logger.warning(f"Invalid token format in {path}")
        return None
    except (json.JSONDecodeError, OSError) as e:
        logger.warning(f"Failed to load token from {path}: {e}")
        return None


def save_token(provider: str, token: dict) -> None:
    """Save OAuth token to local storage with secure permissions.

    File permissions: 0600 (owner read/write only)
    Directory permissions: 0700 (owner read/write/execute only)
    """
    token_dir = _get_token_dir()
    token_dir.mkdir(parents=True, exist_ok=True)

    # Secure directory permissions (Unix only)
    if os.name != "nt":  # pragma: no cover
        try:
            token_dir.chmod(stat.S_IRWXU)  # 0700
        except OSError:
            pass

    path = get_token_path(provider)
    path.write_text(json.dumps(token, indent=2), encoding="utf-8")

    # Secure file permissions (Unix only)
    if os.name != "nt":  # pragma: no cover
        try:
            path.chmod(stat.S_IRUSR | stat.S_IWUSR)  # 0600
        except OSError:
            pass

    logger.info(f"Token saved: {path}")


def delete_token(provider: str) -> bool:
    """Delete stored OAuth token for a provider.

    Returns True if deleted (or not found), False on error.
    """
    path = get_token_path(provider)
    try:
        path.unlink(missing_ok=True)
        return True
    except OSError as e:
        logger.warning(f"Failed to delete token from {path}: {e}")
        return False
