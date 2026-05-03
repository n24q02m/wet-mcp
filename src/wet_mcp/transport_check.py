"""Transport / runtime venv detection helpers.

Stdio uvx native invocation (`uvx wet-mcp`) places the server inside a
uv-managed tool venv that ships without `pip`. The web-core SearXNG
runner relies on `pip install` and a Docker fallback that neither is
available nor reliable in that context (see spec
``2026-05-01-stdio-pure-http-multiuser.md`` §4.1.1).

This module provides a single memoized predicate, :func:`is_uvx_tool_venv`,
used to short-circuit ``web.search`` / ``research`` / ``docs`` / ``similar``
actions with a clear error message in stdio uvx mode. Other actions
(``extract`` / ``crawl`` / ``map`` / ``media``) remain available because
they hit upstream HTTP directly via ``httpx`` and require no SearXNG.
"""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

_UVX_TOOL_VENV_CACHE: bool | None = None


def is_uvx_tool_venv() -> bool:
    """Return True when the current interpreter lives in a uvx tool venv.

    Detection is layered to avoid false positives:

    1. **Docker short-circuit**: if ``/.dockerenv`` exists (every Docker
       container has this marker file), return ``False`` immediately. The
       wet-mcp Docker image uses ``uv sync`` which produces a venv WITHOUT
       pip — that signal would otherwise trigger detection #3 below and
       reject SearXNG-dependent actions even though Method 3 stdio Docker
       has full Docker daemon access.
    2. **Path-based positive**: ``sys.executable`` contains the
       ``uv/tools/`` segment used by uv on Linux/Mac
       (``~/.local/share/uv/tools/<name>/...``) or Windows
       (``%APPDATA%/uv/tools/<name>/...``).
    3. **Module-based fallback**: ``importlib.util.find_spec("pip")``
       returns ``None`` — uv tool venvs deliberately omit pip, while
       normal pip-managed venvs keep it. Only checked if not in Docker.

    Either path/module signal alone is sufficient. Result is memoized for
    the lifetime of the process.
    """
    global _UVX_TOOL_VENV_CACHE
    if _UVX_TOOL_VENV_CACHE is not None:
        return _UVX_TOOL_VENV_CACHE

    _UVX_TOOL_VENV_CACHE = _detect_uvx_tool_venv()
    return _UVX_TOOL_VENV_CACHE


def _is_in_docker() -> bool:
    """Detect Docker container runtime via the standard ``/.dockerenv`` marker.

    Docker creates this file in every container regardless of base image,
    so it is the most reliable cross-distro signal. Podman creates it too
    when running with Docker compatibility mode.
    """
    return os.path.exists("/.dockerenv")


def _detect_uvx_tool_venv() -> bool:
    """Run the actual detection (no caching). Exposed for tests."""
    # Docker short-circuit: containers running ``uv sync`` images would
    # otherwise trip the no-pip fallback even though they have Docker
    # daemon access for SearXNG.
    if _is_in_docker():
        return False

    # Path-based check: uv installs tool venvs under a "uv/tools/" directory
    # on every platform. ``Path.parts`` works regardless of separator quirks.
    try:
        parts = Path(sys.executable).resolve().parts
    except (OSError, ValueError):
        parts = ()

    for i in range(len(parts) - 1):
        if parts[i].lower() == "uv" and parts[i + 1].lower() == "tools":
            return True

    # Module-based check: uv tool venvs ship without pip.
    if importlib.util.find_spec("pip") is None:
        return True

    return False


def reset_cache() -> None:
    """Clear the memoized detection result.

    Tests use this between cases that monkeypatch ``sys.executable`` or
    ``importlib.util.find_spec``. Production code never calls this.
    """
    global _UVX_TOOL_VENV_CACHE
    _UVX_TOOL_VENV_CACHE = None


# Error message returned by tools when SearXNG-dependent actions are
# invoked from inside a uvx tool venv. Per spec
# ``2026-05-01-stdio-pure-http-multiuser.md`` §4.1.1.
UVX_SEARXNG_BLOCKED_ERROR = (
    "Error: action '{action}' requires SearXNG which is not available in "
    "stdio uvx mode.\n"
    "Options:\n"
    "  1. Run via Docker (Method 3 stdio Docker): "
    "docker run -i --rm -e ENV n24q02m/wet-mcp:latest\n"
    "  2. Run via HTTP mode (Method 2 HTTP Docker recommended): "
    "docker run -p 8080:8080 n24q02m/wet-mcp:latest --http\n"
    "See https://github.com/n24q02m/wet-mcp#setup for details."
)


def uvx_searxng_blocked_error(action: str) -> str:
    """Format the SearXNG-blocked error message for ``action``."""
    return UVX_SEARXNG_BLOCKED_ERROR.format(action=action)
