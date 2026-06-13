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


def _validate_safe_name(name: str) -> None:
    """Validate that a name does not contain path separators or traversal sequences."""
    if not name:
        raise ValueError("Name cannot be empty")
    if "/" in name or "\\" in name or ".." in name:
        raise ValueError(f"Invalid path component: {name}")


def get_token_dir() -> Path:
    """Get directory for token storage (~/.wet-mcp/tokens/).

    Single-user (default) layout. Multi-user remote mode uses
    :func:`get_token_dir_for_sub` instead so concurrent JWT subjects
    do not share GDrive tokens.
    """
    return settings.get_data_dir() / "tokens"


def get_token_path(provider: str) -> Path:
    """Return the secure file path for a provider token."""
    _validate_safe_name(provider)
    return get_token_dir() / f"{provider}.json"


def get_token_dir_for_sub(sub: str) -> Path:
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
    return get_token_dir_for_sub(sub) / f"{provider}.json"


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

    # Windows: fully-qualify user as DOMAIN\user so icacls does not collide
    # with the local machine account when username matches hostname.
    try:
        user = getpass.getuser()
        if not user:
            logger.warning(
                f"Cannot determine current user for icacls on {path}; leaving default ACL"
            )
            return
        domain = os.environ.get("USERDOMAIN", "")
        principal = f"{domain}\\{user}" if domain else user
        result = subprocess.run(
            ["icacls", str(path), "/inheritance:r", "/grant:r", f"{principal}:F"],
            capture_output=True,
            check=False,
        )
        if result.returncode != 0:
            stderr_text = (
                result.stderr.decode("utf-8", errors="ignore") if result.stderr else ""
            )
            logger.warning(
                f"icacls failed for {path} (principal={principal}): {stderr_text.strip()} "
                f"-- ACL may be inaccessible, rolling back /inheritance:r"
            )
            # Best-effort rollback: re-enable inheritance so dir is at least accessible
            subprocess.run(
                ["icacls", str(path), "/inheritance:e"],
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
    token_dir = get_token_dir()
    token_dir.mkdir(parents=True, exist_ok=True)
    _set_secure_permissions(token_dir)

    path = get_token_path(provider)
    path.write_text(json.dumps(token, indent=2), encoding="utf-8")
    _set_secure_permissions(path)

    logger.info(f"Token saved: {path}")


def save_token_for_sub(sub: str, provider: str, token: dict) -> None:
    """Save OAuth token under the per-sub directory.

    Used by multi-user remote mode so concurrent users do not share a
    single GDrive refresh-token. Same 0600 / 0700 hardening as the
    single-user path.
    """
    token_dir = get_token_dir_for_sub(sub)
    token_dir.mkdir(parents=True, exist_ok=True)
    _set_secure_permissions(token_dir)

    path = get_token_path_for_sub(sub, provider)
    path.write_text(json.dumps(token, indent=2), encoding="utf-8")
    _set_secure_permissions(path)

    logger.info(f"Token saved (sub={sub}): {path}")


def load_token_for_sub(sub: str, provider: str) -> dict | None:
    """Load a per-sub OAuth token. Returns None when absent or malformed."""
    path = get_token_path_for_sub(sub, provider)
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


# Spec naming alias: the HTTP multi-user wiring spec
# (``2026-05-01-stdio-pure-http-multiuser.md``) refers to ``read_token_for_sub``
# as the mirror of ``save_token_for_sub``. Keep both names available so
# call sites can use whichever reads more clearly in context.
read_token_for_sub = load_token_for_sub
