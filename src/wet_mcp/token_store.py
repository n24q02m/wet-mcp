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


def _set_secure_permissions(path: Path, is_dir: bool = False) -> None:
    """Set secure file/directory permissions (Unix: 0600/0700, Windows: ACLs)."""
    if os.name == "nt":
        try:
            # On Windows, use icacls to:
            # 1. /inheritance:r - Remove all inherited ACEs
            # 2. /grant:r <user>:F - Grant Full control to current user only
            user = getpass.getuser()
            subprocess.run(
                ["icacls", str(path), "/inheritance:r", "/grant:r", f"{user}:F"],
                check=True,
                capture_output=True,
            )
        except (subprocess.CalledProcessError, OSError) as e:
            logger.warning(
                f"Failed to set secure permissions on {path} via icacls: {e}"
            )
    else:
        try:
            # Unix: 0700 for dirs, 0600 for files
            mode = stat.S_IRWXU if is_dir else (stat.S_IRUSR | stat.S_IWUSR)
            path.chmod(mode)
        except OSError as e:
            logger.warning(f"Failed to set secure permissions on {path}: {e}")


def save_token(provider: str, token: dict) -> None:
    """Save OAuth token to local storage with secure permissions.

    File permissions: 0600 (owner read/write only)
    Directory permissions: 0700 (owner read/write/execute only)
    """
    token_dir = _get_token_dir()
    token_dir.mkdir(parents=True, exist_ok=True)
    _set_secure_permissions(token_dir, is_dir=True)

    path = get_token_path(provider)
    path.write_text(json.dumps(token, indent=2), encoding="utf-8")
    _set_secure_permissions(path, is_dir=False)

    logger.info(f"Token saved: {path}")
