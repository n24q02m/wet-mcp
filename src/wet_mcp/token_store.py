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

import getpass
import json
import os
import stat
import subprocess
from pathlib import Path

from loguru import logger

from wet_mcp.config import settings


def _get_token_dir() -> Path:
    """Get directory for token storage (~/.wet-mcp/tokens/)."""
    return settings.get_data_dir() / "tokens"


def get_token_path(provider: str) -> Path:
    """Get path for a provider's token file."""
    return _get_token_dir() / f"{provider}.json"


def _set_secure_permissions(path: Path) -> None:
    """Restrict access to owner-only.

    Unix: chmod 0700 for directories, 0600 for files.
    Windows: icacls /inheritance:r + /grant:r <user>:F -- remove inherited
    ACEs and grant full control to the current user only, so other local
    users cannot read token files even when stored under the user profile.
    """
    if os.name != "nt":
        try:
            if path.is_dir():
                path.chmod(stat.S_IRWXU)  # 0700
            else:
                path.chmod(stat.S_IRUSR | stat.S_IWUSR)  # 0600
        except OSError as e:
            logger.debug(f"chmod failed for {path}: {e}")
        return

    try:
        user = getpass.getuser()
        subprocess.run(
            ["icacls", str(path), "/inheritance:r", "/grant:r", f"{user}:F"],
            capture_output=True,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as e:
        logger.debug(f"icacls failed for {path}: {e}")


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
    _set_secure_permissions(token_dir)

    path = get_token_path(provider)
    path.write_text(json.dumps(token, indent=2), encoding="utf-8")
    _set_secure_permissions(path)

    logger.info(f"Token saved: {path}")
