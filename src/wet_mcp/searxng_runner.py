"""Embedded SearXNG process management — delegates to web-core.

Bridges wet-mcp settings (``config.settings``) to web-core's
``ensure_searxng`` API. Also monkey-patches web-core's SearXNG
installer to apply wet-mcp-specific patches (version_frozen +
Windows valkeydb compatibility).

All internal functions are re-exported from web-core for backward
compatibility with existing tests and consumers.
"""

import asyncio
import atexit
import os
import subprocess
import sys

import web_core.search.runner as _wc_runner
from loguru import logger
from web_core.search.runner import shutdown_searxng

from wet_mcp.config import settings

# ---------------------------------------------------------------------------
# Monkey-patch web-core's SearXNG installer to apply wet-mcp patches.
# web-core's _install_searxng() does not create version_frozen.py or
# patch valkeydb.py for Windows. These are needed when installing
# SearXNG from zip archive.
# ---------------------------------------------------------------------------

_wc_original_install = _wc_runner._install_searxng


def _patched_install_searxng() -> bool:
    """Install SearXNG via web-core then apply wet-mcp patches."""
    result = _wc_original_install()
    if result:
        try:
            from wet_mcp.setup import (
                patch_searxng_version,
                patch_searxng_windows,
            )

            patch_searxng_version()
            patch_searxng_windows()
        except Exception as e:
            logger.debug(f"SearXNG patch failed (non-fatal): {e}")
    return result


_wc_runner._install_searxng = _patched_install_searxng  # type: ignore[assignment]  # ty: ignore[invalid-assignment]


# ---------------------------------------------------------------------------
# Randomize port discovery to avoid TOCTOU race when multiple instances
# start concurrently (e.g. wet, wet-nokey, wet-sync).
# ---------------------------------------------------------------------------


def _find_available_port(start_port: int, max_tries: int = 100) -> int:
    """Find an available port, randomizing offset to avoid collisions."""
    import random
    import socket

    offsets = list(range(max_tries))
    random.shuffle(offsets)

    for offset in offsets:
        port = start_port + offset
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(("127.0.0.1", port))
                return port
        except OSError:
            continue

    msg = f"No available port found in range {start_port}-{start_port + max_tries - 1}"
    raise RuntimeError(msg)


# ---------------------------------------------------------------------------
# PERFORMANCE FIX: Monkey-patch async callers to use asyncio.to_thread for
# blocking termination logic (_force_kill_process).
# ---------------------------------------------------------------------------


async def _patched_ensure_searxng_locked(*, auto_start: bool, start_port: int) -> str:
    """Non-blocking version of _ensure_searxng_locked."""
    # Fast path: our own process is alive and port is known.
    if (
        _wc_runner._is_process_alive()
        and _wc_runner._searxng_port is not None
        and _wc_runner._searxng_process is not None
    ):
        url = f"http://127.0.0.1:{_wc_runner._searxng_port}"
        if await _wc_runner._quick_health_check(url, retries=1):
            logger.debug("SearXNG already running at %s", url)
            return url
        # Process alive but not serving -- kill and restart.
        logger.warning(
            "SearXNG process alive (PID=%d) but not healthy at %s, killing",
            _wc_runner._searxng_process.pid,
            url,
        )
        await asyncio.to_thread(
            _wc_runner._force_kill_process, _wc_runner._searxng_process
        )
        _wc_runner._searxng_process = None
        _wc_runner._searxng_port = None

    # Try reusing existing SearXNG from another process.
    reused_url = await _wc_runner._try_reuse_existing()
    if reused_url:
        logger.info("Reusing existing SearXNG instance at %s", reused_url)
        return reused_url

    if not auto_start:
        msg = "No running SearXNG instance found and auto_start is disabled"
        raise RuntimeError(msg)

    # Process is dead or not started -- need to (re)start.
    return await _wc_runner._handle_restart_and_start(start_port=start_port)


async def _patched_start_searxng_subprocess(start_port: int) -> str | None:
    """Non-blocking version of _start_searxng_subprocess."""
    # Kill any existing process first.
    if _wc_runner._searxng_process is not None:
        await asyncio.to_thread(
            _wc_runner._force_kill_process, _wc_runner._searxng_process
        )
        _wc_runner._searxng_process = None
        _wc_runner._searxng_port = None

    try:
        # Find available port.
        port = await asyncio.to_thread(_wc_runner._find_available_port, start_port)
        if port != start_port:
            logger.info("Port %d in use, using %d", start_port, port)

        # Kill any stale process on the target port.
        await asyncio.to_thread(_wc_runner._kill_stale_port_process, port)
        await asyncio.sleep(0.5)

        _wc_runner._searxng_port = port

        # Write settings with correct port.
        settings_path = await asyncio.to_thread(_wc_runner._get_settings_path, port)

        # Build environment for SearXNG.
        env = os.environ.copy()
        env["SEARXNG_SETTINGS_PATH"] = str(settings_path)

        logger.info("Starting SearXNG on port %d...", port)

        # On Windows, stderr=PIPE without a reader causes a deadlock.
        stderr_target = (
            subprocess.DEVNULL if sys.platform == "win32" else subprocess.PIPE
        )

        # On Windows, use waitress instead of Flask's Werkzeug dev server.
        if sys.platform == "win32":
            cmd = [
                sys.executable,
                "-c",
                (
                    "from waitress import serve;"
                    " from searx.webapp import app;"
                    f" serve(app,"
                    f" host='127.0.0.1', port={port},"
                    f" threads=8, channel_timeout=120,"
                    f" cleanup_interval=30)"
                ),
            ]
        else:
            cmd = [sys.executable, "-m", "searx.webapp"]

        _wc_runner._searxng_process = await asyncio.to_thread(
            lambda: subprocess.Popen(
                cmd,
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=stderr_target,
                **_wc_runner._get_process_kwargs(),
            )
        )

        # Register cleanup (idempotent -- atexit deduplicates internally).
        atexit.register(_wc_runner._cleanup_process)

        url = f"http://127.0.0.1:{port}"

        # Wait for SearXNG to be healthy.
        if await _wc_runner._wait_for_service(
            url, timeout=_wc_runner._STARTUP_HEALTH_TIMEOUT
        ):
            logger.info("SearXNG ready at %s", url)
            await asyncio.to_thread(
                _wc_runner._write_discovery, port, _wc_runner._searxng_process.pid
            )
            _wc_runner._is_owner = True
            return url

        # Health check timed out.
        logger.warning("SearXNG started but not healthy at %s", url)
        if _wc_runner._searxng_process.poll() is not None:
            if _wc_runner._searxng_process.stderr:
                stderr_raw = await asyncio.to_thread(
                    _wc_runner._searxng_process.stderr.read
                )
                stderr = stderr_raw.decode()
            else:
                stderr = ""
            logger.error("SearXNG process exited during startup: %s", stderr[:500])
        else:
            logger.warning(
                "SearXNG process (PID=%d) alive but not serving, killing stuck process",
                _wc_runner._searxng_process.pid,
            )
            await asyncio.to_thread(
                _wc_runner._force_kill_process, _wc_runner._searxng_process
            )
        _wc_runner._searxng_process = None
        _wc_runner._searxng_port = None
        return None

    except Exception as e:
        logger.error("Failed to start SearXNG subprocess: %s", e)
        if _wc_runner._searxng_process is not None:
            await asyncio.to_thread(
                _wc_runner._force_kill_process, _wc_runner._searxng_process
            )
            _wc_runner._searxng_process = None
            _wc_runner._searxng_port = None
        return None


_wc_runner._ensure_searxng_locked = _patched_ensure_searxng_locked  # type: ignore[assignment]  # ty: ignore[invalid-assignment]
_wc_runner._start_searxng_subprocess = _patched_start_searxng_subprocess  # type: ignore[assignment]  # ty: ignore[invalid-assignment]

_wc_runner._find_available_port = _find_available_port  # type: ignore[assignment]  # ty: ignore[invalid-assignment]

# ---------------------------------------------------------------------------
# Re-export internal functions from web-core for backward compatibility.
# Tests and other modules import these from wet_mcp.searxng_runner.
# ---------------------------------------------------------------------------
from web_core.search.runner import (  # noqa: F401, E402
    _DISCOVERY_FILE,
    _HEALTH_CHECK_TIMEOUT,
    _MAX_RESTART_ATTEMPTS,
    _RESTART_COOLDOWN,
    _STARTUP_HEALTH_TIMEOUT,
    _cleanup_process,
    _ensure_searxng_locked,
    _find_available_port,
    _force_kill_process,
    _get_pip_command,
    _get_process_kwargs,
    _get_settings_path,
    _get_startup_lock,
    _handle_restart_and_start,
    _install_searxng,
    _is_owner,
    _is_pid_alive,
    _is_process_alive,
    _is_searxng_installed,
    _kill_stale_port_process,
    _last_restart_time,
    _quick_health_check,
    _read_discovery,
    _remove_discovery,
    _restart_count,
    _searxng_port,
    _searxng_process,
    _sigterm_then_kill,
    _start_searxng_subprocess,
    _startup_lock,
    _try_reuse_existing,
    _wait_for_service,
    _write_discovery,
)

# ---------------------------------------------------------------------------
# Public API — bridges wet-mcp settings to web-core
# ---------------------------------------------------------------------------


async def ensure_searxng() -> str:
    """Start embedded SearXNG subprocess if not running. Returns URL.

    Bridges wet-mcp settings to web-core's ensure_searxng API:
    - ``settings.wet_auto_searxng`` -> ``auto_start``
    - ``settings.searxng_url`` -> ``url`` (when auto disabled)
    - ``settings.wet_searxng_port`` -> ``start_port``

    Falls back to ``settings.searxng_url`` on failure.
    """
    if not settings.wet_auto_searxng:
        logger.info("Auto SearXNG disabled, using external URL")
        return settings.searxng_url

    try:
        return await _wc_runner.ensure_searxng(
            start_port=settings.wet_searxng_port,
        )
    except RuntimeError as e:
        logger.warning(f"SearXNG start failed: {e}. Falling back to external URL.")
        return settings.searxng_url


def stop_searxng() -> None:
    """Stop SearXNG subprocess if running."""
    shutdown_searxng()
