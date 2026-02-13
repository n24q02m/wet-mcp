"""Embedded SearXNG process management.

Replaces Docker-based SearXNG with a subprocess running directly from
the installed SearXNG Python package. SearXNG is auto-installed from
GitHub on first run if not already available.

On Windows, valkeydb.py is patched to remove Unix-only ``pwd`` dependency.

Resilience features:
- Auto-restart on crash detection (poll() check)
- Force-kill stale processes before restart to avoid port conflicts
- Health check verification after (re)start
- Configurable max restart attempts to prevent restart loops
"""

import asyncio
import atexit
import os
import signal
import socket
import subprocess
import sys
import time
from importlib.resources import files
from pathlib import Path

import httpx
from loguru import logger

from wet_mcp.config import settings
from wet_mcp.setup import install_searxng

# Maximum number of restart attempts before giving up and falling back
# to the external SearXNG URL.
_MAX_RESTART_ATTEMPTS = 3

# Cooldown between restart attempts (seconds).
_RESTART_COOLDOWN = 2.0

# Health check timeout per probe (seconds).
_HEALTH_CHECK_TIMEOUT = 2.0

# Maximum time to wait for SearXNG to become healthy after start (seconds).
_STARTUP_HEALTH_TIMEOUT = 60.0


# Module-level process reference for cleanup
_searxng_process: subprocess.Popen | None = None
_searxng_port: int | None = None
_restart_count: int = 0
_last_restart_time: float = 0.0


def _find_available_port(start_port: int, max_tries: int = 10) -> int:
    """Find an available port starting from start_port."""
    for offset in range(max_tries):
        port = start_port + offset
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(("127.0.0.1", port))
                return port
        except OSError:
            continue
    return start_port


async def _wait_for_service(url: str, timeout: float = _STARTUP_HEALTH_TIMEOUT) -> bool:
    """Wait for SearXNG service to be healthy via async HTTP check."""
    start_time = time.time()
    logger.debug(f"Waiting for SearXNG at {url}...")

    async with httpx.AsyncClient() as client:
        while time.time() - start_time < timeout:
            try:
                response = await client.get(
                    f"{url}/healthz",
                    headers={
                        "X-Real-IP": "127.0.0.1",
                        "X-Forwarded-For": "127.0.0.1",
                    },
                    timeout=_HEALTH_CHECK_TIMEOUT,
                )
                if response.status_code == 200:
                    return True
            except Exception:
                pass
            await asyncio.sleep(1.0)
    return False


def _get_settings_path(port: int) -> Path:
    """Get path to SearXNG settings file.

    Uses per-process file to avoid write conflicts when multiple
    server instances run simultaneously.
    """
    config_dir = Path.home() / ".wet-mcp"
    config_dir.mkdir(parents=True, exist_ok=True)

    # Per-process settings file (avoids race condition between instances)
    settings_file = config_dir / f"searxng_settings_{os.getpid()}.yml"

    # Always write settings to ensure port is up-to-date
    bundled = files("wet_mcp").joinpath("searxng_settings.yml")
    content = bundled.read_text()

    # Inject the actual port
    content = content.replace(
        "port: 8080",
        f"port: {port}",
    )

    settings_file.write_text(content)
    logger.debug(f"SearXNG settings written to: {settings_file}")

    return settings_file


def _force_kill_process(proc: subprocess.Popen) -> None:
    """Force-kill a subprocess and all its children.

    Tries graceful SIGTERM first, then SIGKILL after a short timeout.
    On Unix, kills the entire process group to avoid orphaned children.
    """
    if proc.poll() is not None:
        return  # Already dead

    pid = proc.pid
    logger.debug(f"Force-killing SearXNG process (PID={pid})...")

    try:
        if sys.platform != "win32":
            # Kill the entire process group on Unix
            try:
                os.killpg(os.getpgid(pid), signal.SIGTERM)
            except (ProcessLookupError, PermissionError):
                proc.terminate()
        else:
            proc.terminate()

        # Wait briefly for graceful shutdown
        try:
            proc.wait(timeout=3)
            logger.debug(f"SearXNG process (PID={pid}) terminated gracefully")
            return
        except subprocess.TimeoutExpired:
            pass

        # Force kill
        if sys.platform != "win32":
            try:
                os.killpg(os.getpgid(pid), signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                proc.kill()
        else:
            proc.kill()

        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            logger.warning(f"SearXNG process (PID={pid}) could not be killed")

        logger.debug(f"SearXNG process (PID={pid}) force-killed")

    except Exception as e:
        logger.debug(f"Error killing SearXNG process: {e}")


def _kill_stale_port_process(port: int) -> None:
    """Kill any process still holding the target port.

    This prevents 'address already in use' errors when restarting
    after a crash that left a zombie process behind.
    """
    if sys.platform == "win32":
        # On Windows, use netstat to find the PID
        try:
            result = subprocess.run(
                ["netstat", "-ano"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            for line in result.stdout.splitlines():
                if f"127.0.0.1:{port}" in line and "LISTENING" in line:
                    parts = line.split()
                    pid_str = parts[-1]
                    try:
                        pid = int(pid_str)
                        if pid > 0:
                            os.kill(pid, signal.SIGTERM)
                            logger.debug(
                                f"Killed stale process on port {port} (PID={pid})"
                            )
                    except (ValueError, ProcessLookupError, PermissionError):
                        pass
        except Exception:
            pass
    else:
        # On Unix, use lsof or fuser
        try:
            result = subprocess.run(
                ["lsof", "-ti", f":{port}"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0 and result.stdout.strip():
                for pid_str in result.stdout.strip().splitlines():
                    try:
                        pid = int(pid_str.strip())
                        if pid > 0 and pid != os.getpid():
                            os.kill(pid, signal.SIGTERM)
                            logger.debug(
                                f"Killed stale process on port {port} (PID={pid})"
                            )
                    except (ValueError, ProcessLookupError, PermissionError):
                        pass
        except FileNotFoundError:
            # lsof not available, try fuser
            try:
                subprocess.run(
                    ["fuser", "-k", f"{port}/tcp"],
                    capture_output=True,
                    timeout=5,
                )
            except (FileNotFoundError, subprocess.TimeoutExpired):
                pass
        except Exception:
            pass


def _cleanup_process() -> None:
    """Cleanup SearXNG subprocess and per-process settings file on exit."""
    global _searxng_process, _searxng_port
    if _searxng_process is not None:
        try:
            logger.debug("Stopping SearXNG subprocess...")
            _force_kill_process(_searxng_process)
            logger.debug("SearXNG subprocess stopped")
        except Exception as e:
            logger.debug(f"Error stopping SearXNG: {e}")
        finally:
            _searxng_process = None
            _searxng_port = None

    # Cleanup per-process settings file
    try:
        pid_settings = Path.home() / ".wet-mcp" / f"searxng_settings_{os.getpid()}.yml"
        if pid_settings.exists():
            pid_settings.unlink()
    except Exception:
        pass


def _is_process_alive() -> bool:
    """Check if the SearXNG subprocess is still running."""
    global _searxng_process
    return _searxng_process is not None and _searxng_process.poll() is None


async def _start_searxng_subprocess() -> str | None:
    """Start a fresh SearXNG subprocess.

    Returns the URL if started successfully, None on failure.
    Handles port conflicts by killing stale processes first.
    """
    global _searxng_process, _searxng_port

    # Kill any existing process first
    if _searxng_process is not None:
        _force_kill_process(_searxng_process)
        _searxng_process = None
        _searxng_port = None

    try:
        # Find available port
        port = await asyncio.to_thread(_find_available_port, settings.wet_searxng_port)
        if port != settings.wet_searxng_port:
            logger.info(f"Port {settings.wet_searxng_port} in use, using {port}")

        # Kill any stale process on the target port
        await asyncio.to_thread(_kill_stale_port_process, port)
        # Brief pause to let the port be released
        await asyncio.sleep(0.5)

        _searxng_port = port

        # Write settings with correct port
        settings_path = await asyncio.to_thread(_get_settings_path, port)

        # Build environment for SearXNG
        env = os.environ.copy()
        env["SEARXNG_SETTINGS_PATH"] = str(settings_path)

        # Start SearXNG subprocess
        logger.info(f"Starting SearXNG on port {port}...")

        _searxng_process = await asyncio.to_thread(
            lambda: subprocess.Popen(
                [sys.executable, "-m", "searx.webapp"],
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                # Use process group on Unix for clean shutdown
                **(_get_process_kwargs()),
            )
        )

        # Register cleanup (idempotent — atexit deduplicates internally)
        atexit.register(_cleanup_process)

        url = f"http://127.0.0.1:{port}"

        # Wait for SearXNG to be healthy
        if await _wait_for_service(url, timeout=_STARTUP_HEALTH_TIMEOUT):
            logger.info(f"SearXNG ready at {url}")
        else:
            logger.warning(f"SearXNG started but not healthy at {url}")
            # Check if process crashed during startup
            if _searxng_process.poll() is not None:
                stderr = (
                    _searxng_process.stderr.read().decode()
                    if _searxng_process.stderr
                    else ""
                )
                logger.error(f"SearXNG process exited during startup: {stderr[:500]}")
                _searxng_process = None
                _searxng_port = None
                return None

        return url

    except Exception as e:
        logger.error(f"Failed to start SearXNG subprocess: {e}")
        if _searxng_process is not None:
            _force_kill_process(_searxng_process)
            _searxng_process = None
            _searxng_port = None
        return None


async def ensure_searxng() -> str:
    """Start embedded SearXNG subprocess if not running. Returns URL.

    This function handles:
    - Auto-installation of SearXNG package from GitHub on first run
    - Subprocess lifecycle management with crash detection
    - Automatic restart on crash (up to _MAX_RESTART_ATTEMPTS)
    - Port conflict resolution (kills stale processes)
    - SearXNG configuration via settings.yml
    - Graceful fallback to external SearXNG URL
    """
    global _searxng_process, _searxng_port, _restart_count, _last_restart_time

    if not settings.wet_auto_searxng:
        logger.info("Auto SearXNG disabled, using external URL")
        return settings.searxng_url

    # Fast path: process is alive and port is known
    if _is_process_alive() and _searxng_port is not None:
        url = f"http://127.0.0.1:{_searxng_port}"
        logger.debug(f"SearXNG already running at {url}")
        return url

    # Process is dead or not started — need to (re)start
    if _searxng_process is not None:
        # Process existed but crashed
        exit_code = _searxng_process.poll()
        stderr_output = ""
        if _searxng_process.stderr:
            try:
                stderr_output = _searxng_process.stderr.read().decode(errors="replace")[
                    :500
                ]
            except Exception:
                pass
        logger.warning(
            f"SearXNG process crashed (exit_code={exit_code}). stderr: {stderr_output}"
        )
        _searxng_process = None

    # Reset restart counter if enough time has passed since last restart
    now = time.time()
    if now - _last_restart_time > 300:  # 5 minutes
        _restart_count = 0

    # Check restart budget
    if _restart_count >= _MAX_RESTART_ATTEMPTS:
        logger.error(
            f"SearXNG restart limit reached ({_MAX_RESTART_ATTEMPTS} attempts). "
            "Falling back to external URL."
        )
        return settings.searxng_url

    # Ensure SearXNG package is installed
    if not await asyncio.to_thread(install_searxng):
        logger.warning("SearXNG installation failed, using external URL")
        return settings.searxng_url

    # Attempt to start with cooldown between restarts
    if _restart_count > 0:
        cooldown = _RESTART_COOLDOWN * _restart_count
        logger.info(
            f"Waiting {cooldown:.1f}s before SearXNG restart attempt {_restart_count + 1}..."
        )
        await asyncio.sleep(cooldown)

    _restart_count += 1
    _last_restart_time = time.time()

    url = await _start_searxng_subprocess()
    if url is not None:
        # Successful start — reset restart counter
        _restart_count = 0
        return url

    logger.warning("SearXNG start failed, falling back to external URL")
    return settings.searxng_url


def _get_process_kwargs() -> dict:
    """Get platform-specific subprocess kwargs."""
    if sys.platform != "win32":
        return {"preexec_fn": os.setsid}
    else:
        return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}


def stop_searxng() -> None:
    """Stop SearXNG subprocess if running."""
    _cleanup_process()


def remove_searxng() -> None:
    """Stop SearXNG subprocess (alias for compatibility)."""
    _cleanup_process()
