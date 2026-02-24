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
- Shared instance: multiple MCP server instances reuse one SearXNG process
- Eager startup: SearXNG starts in lifespan background, ready before first search
"""

import asyncio
import atexit
import json as _json
import os
import shutil
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
from wet_mcp.setup import patch_searxng_version, patch_searxng_windows

# Maximum number of restart attempts before giving up and falling back
# to the external SearXNG URL.
_MAX_RESTART_ATTEMPTS = 3

# Cooldown between restart attempts (seconds).
_RESTART_COOLDOWN = 2.0

# Health check timeout per probe (seconds).
_HEALTH_CHECK_TIMEOUT = 2.0

# Maximum time to wait for SearXNG to become healthy after start (seconds).
# Cold start (first run) includes package installation + Flask init which can
# take 90-120s on slow machines.  Give enough headroom so the first search
# call does not time out.
_STARTUP_HEALTH_TIMEOUT = 120.0

# Discovery file for sharing SearXNG across multiple MCP server instances.
# Contains {pid, port, owner_pid, started_at} of the running SearXNG process.
_DISCOVERY_FILE = Path.home() / ".wet-mcp" / "searxng_instance.json"


def _get_pip_command() -> list[str]:
    """Get cross-platform pip install command.

    Priority:
    1. uv pip (for uv environments - no pip module)
    2. pip (for traditional venvs)
    3. python -m pip (fallback)
    """
    # Check uv first (cross-platform, works in uv venvs without pip)
    uv_path = shutil.which("uv")
    if uv_path:
        return [uv_path, "pip", "install", "--python", sys.executable]

    # Check pip executable
    pip_path = shutil.which("pip")
    if pip_path:
        return [pip_path, "install"]

    # Fallback to python -m pip
    return [sys.executable, "-m", "pip", "install"]


# SearXNG install URL (zip archive avoids git filename issues on Windows)
_SEARXNG_INSTALL_URL = (
    "https://github.com/searxng/searxng/archive/refs/heads/master.zip"
)

# Module-level process reference for cleanup
_searxng_process: subprocess.Popen | None = None
_searxng_port: int | None = None
_restart_count: int = 0
_last_restart_time: float = 0.0

# Shared instance tracking
_is_owner: bool = False  # True if this instance started the SearXNG process
_startup_lock: asyncio.Lock | None = None  # Lazy-init to avoid event loop issues


def _get_startup_lock() -> asyncio.Lock:
    """Get or create the startup lock (lazy init for event loop safety)."""
    global _startup_lock
    if _startup_lock is None:
        _startup_lock = asyncio.Lock()
    return _startup_lock


# ---------------------------------------------------------------------------
# Shared instance discovery
# ---------------------------------------------------------------------------


def _is_pid_alive(pid: int) -> bool:
    """Check if a process with the given PID is alive."""
    if sys.platform == "win32":
        # os.kill(pid, 0) does not work on Windows for non-child processes.
        # Use ctypes OpenProcess to check if PID exists.
        import ctypes

        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        handle = ctypes.windll.kernel32.OpenProcess(
            PROCESS_QUERY_LIMITED_INFORMATION, False, pid
        )
        if handle:
            ctypes.windll.kernel32.CloseHandle(handle)
            return True
        return False
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError, OSError):
        return False


def _read_discovery() -> dict | None:
    """Read SearXNG discovery file.

    Returns dict with {pid, port, owner_pid, started_at} or None.
    """
    try:
        if _DISCOVERY_FILE.exists():
            data = _json.loads(_DISCOVERY_FILE.read_text())
            if isinstance(data, dict) and "port" in data and "pid" in data:
                return data
    except Exception:
        pass
    return None


def _write_discovery(port: int, pid: int) -> None:
    """Write SearXNG discovery file for other instances to find."""
    try:
        _DISCOVERY_FILE.parent.mkdir(parents=True, exist_ok=True)
        _DISCOVERY_FILE.write_text(
            _json.dumps(
                {
                    "pid": pid,
                    "port": port,
                    "owner_pid": os.getpid(),
                    "started_at": time.time(),
                }
            )
        )
    except Exception as e:
        logger.debug(f"Failed to write discovery file: {e}")


def _remove_discovery() -> None:
    """Remove discovery file (only called by owner on cleanup)."""
    try:
        if _DISCOVERY_FILE.exists():
            _DISCOVERY_FILE.unlink()
    except Exception:
        pass


async def _quick_health_check(url: str, retries: int = 3) -> bool:
    """Health check against a SearXNG URL with retries.

    Creates a fresh AsyncClient per call.  The first probe after process
    startup can be slow (cold TCP + SearXNG init), so we retry with
    exponential backoff (0.5s, 1s, 2s) and a generous per-probe timeout.
    """
    for attempt in range(retries):
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{url}/healthz",
                    headers={
                        "X-Real-IP": "127.0.0.1",
                        "X-Forwarded-For": "127.0.0.1",
                    },
                    timeout=5.0,
                )
                if response.status_code == 200:
                    return True
        except Exception:
            pass
        if attempt < retries - 1:
            await asyncio.sleep(0.5 * (attempt + 1))
    return False


async def _try_reuse_existing() -> str | None:
    """Try to reuse a SearXNG instance started by another MCP server.

    Reads the discovery file, verifies the process is alive and healthy,
    and returns the URL if reusable.
    """
    data = await asyncio.to_thread(_read_discovery)
    if not data:
        return None

    port = data.get("port")
    pid = data.get("pid")
    if not port or not pid:
        return None

    # Check if the SearXNG process is still alive
    if not _is_pid_alive(pid):
        logger.debug(f"Discovery file points to dead process (PID={pid}), ignoring")
        return None

    # Health check the existing instance
    url = f"http://127.0.0.1:{port}"
    if await _quick_health_check(url):
        return url

    logger.debug(f"Discovery file points to unhealthy instance at {url}, ignoring")
    return None


# ---------------------------------------------------------------------------
# Port management
# ---------------------------------------------------------------------------


def _find_available_port(start_port: int, max_tries: int = 50) -> int:
    """Find an available port, randomizing offset to avoid collisions.

    When multiple WET MCP instances start concurrently (e.g. wet, wet-nokey,
    wet-sync), they all call this function at roughly the same time.
    A deterministic port scan (8080, 8081, ...) can hit a TOCTOU race:
    two instances both see port 8081 as free, then one fails to bind.

    Fix: randomize the starting offset within a wider range so concurrent
    instances are unlikely to pick the same port.
    """
    import random

    # Randomize starting offset to avoid concurrent collisions
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


def _is_searxng_installed() -> bool:
    """Check if the SearXNG Python package is fully installed.

    Uses ``importlib.util.find_spec`` instead of a direct import to avoid
    executing module-level code in ``searx.webapp`` which calls ``sys.exit(1)``
    when ``secret_key`` is unchanged (the default ``ultrasecretkey``).
    """
    import importlib.util

    return importlib.util.find_spec("searx.webapp") is not None


def _install_searxng() -> bool:
    """Install SearXNG from GitHub zip archive.

    Uses zip URL instead of git+ to avoid filename issues on some
    platforms. Pre-installs build dependencies before SearXNG.

    Returns:
        True if installation succeeded.
    """
    logger.info("Installing SearXNG from GitHub (first run)...")

    try:
        pip_cmd = _get_pip_command()
        logger.debug(f"Using pip command: {pip_cmd}")

        # Pre-install build dependencies required by SearXNG
        logger.debug("Installing SearXNG build dependencies...")
        deps_result = subprocess.run(
            [
                *pip_cmd,
                "--quiet",
                "msgspec",
                "setuptools",
                "wheel",
                "pyyaml",
            ],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=120,
        )
        if deps_result.returncode != 0:
            logger.error(f"Build deps installation failed: {deps_result.stderr[:500]}")
            return False

        # Install SearXNG with --no-build-isolation (uses pre-installed deps)
        result = subprocess.run(
            [
                *pip_cmd,
                "--quiet",
                "--no-build-isolation",
                _SEARXNG_INSTALL_URL,
            ],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=300,
        )

        if result.returncode == 0:
            logger.info("SearXNG installed successfully")
            patch_searxng_version()
            patch_searxng_windows()
            return True
        else:
            logger.error(f"SearXNG installation failed: {result.stderr[:500]}")
            return False

    except subprocess.TimeoutExpired:
        logger.error("SearXNG installation timed out")
        return False
    except Exception as e:
        logger.error(f"Failed to install SearXNG: {e}")
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
        "port: 41592",
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
                stdin=subprocess.DEVNULL,
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
                stdin=subprocess.DEVNULL,
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
                    stdin=subprocess.DEVNULL,
                    capture_output=True,
                    timeout=5,
                )
            except (FileNotFoundError, subprocess.TimeoutExpired):
                pass
        except Exception:
            pass


def _cleanup_process() -> None:
    """Cleanup SearXNG subprocess and per-process settings file on exit.

    Only kills SearXNG if this instance owns it (started it).
    Non-owner instances just clear their local references.
    """
    global _searxng_process, _searxng_port, _is_owner
    if _searxng_process is not None:
        if _is_owner:
            try:
                logger.debug("Stopping owned SearXNG subprocess...")
                _force_kill_process(_searxng_process)
                logger.debug("SearXNG subprocess stopped")
            except Exception as e:
                logger.debug(f"Error stopping SearXNG: {e}")
            # Remove discovery file so other instances don't try to reuse
            _remove_discovery()
        else:
            logger.debug("Not owner, leaving SearXNG subprocess running")
        _searxng_process = None
        _searxng_port = None
        _is_owner = False

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
    Writes discovery file so other MCP server instances can reuse this SearXNG.
    """
    global _searxng_process, _searxng_port, _is_owner

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
                stdin=subprocess.DEVNULL,
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
            # Write discovery file so other instances can reuse this SearXNG
            await asyncio.to_thread(_write_discovery, port, _searxng_process.pid)
            _is_owner = True
            return url

        # Health check timed out — process may be stuck or crashed
        logger.warning(f"SearXNG started but not healthy at {url}")
        if _searxng_process.poll() is not None:
            stderr = (
                _searxng_process.stderr.read().decode()
                if _searxng_process.stderr
                else ""
            )
            logger.error(f"SearXNG process exited during startup: {stderr[:500]}")
        else:
            # Process alive but not listening — kill the stuck process
            logger.warning(
                f"SearXNG process (PID={_searxng_process.pid}) alive but not "
                "serving, killing stuck process"
            )
            _force_kill_process(_searxng_process)
        _searxng_process = None
        _searxng_port = None
        return None

    except Exception as e:
        logger.error(f"Failed to start SearXNG subprocess: {e}")
        if _searxng_process is not None:
            _force_kill_process(_searxng_process)
            _searxng_process = None
            _searxng_port = None
        return None


async def _check_active_instance() -> str | None:
    """Check if the currently tracked process is healthy."""
    global _searxng_process, _searxng_port

    if (
        _is_process_alive()
        and _searxng_port is not None
        and _searxng_process is not None
    ):
        url = f"http://127.0.0.1:{_searxng_port}"
        # Verify port is actually responding (process may be stuck)
        if await _quick_health_check(url, retries=1):
            logger.debug(f"SearXNG already running at {url}")
            return url
        # Process alive but not serving — kill and restart
        logger.warning(
            f"SearXNG process alive (PID={_searxng_process.pid}) "
            f"but not healthy at {url}, killing"
        )
        _force_kill_process(_searxng_process)
        _searxng_process = None
        _searxng_port = None
    return None


def _handle_crashed_process() -> None:
    """Log details if the process has crashed."""
    global _searxng_process

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


async def _check_restart_policy() -> bool:
    """Check if we should attempt a restart based on policy."""
    global _restart_count, _last_restart_time

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
        return False

    # Attempt to start with cooldown between restarts
    if _restart_count > 0:
        cooldown = _RESTART_COOLDOWN * _restart_count
        logger.info(
            f"Waiting {cooldown:.1f}s before SearXNG restart attempt {_restart_count + 1}..."
        )
        await asyncio.sleep(cooldown)

    _restart_count += 1
    _last_restart_time = time.time()
    return True


async def _ensure_installation_and_start() -> str | None:
    """Ensure SearXNG is installed and attempt to start it."""
    # Ensure SearXNG package is installed
    if not await asyncio.to_thread(_is_searxng_installed):
        if not await asyncio.to_thread(_install_searxng):
            logger.warning("SearXNG installation failed, using external URL")
            return None

    url = await _start_searxng_subprocess()
    if url is not None:
        return url

    logger.warning("SearXNG start failed, falling back to external URL")
    return None


async def ensure_searxng() -> str:
    """Start embedded SearXNG subprocess if not running. Returns URL.

    This function handles:
    - Reuse of existing SearXNG from other MCP server instances (shared instance)
    - Auto-installation of SearXNG package from GitHub on first run
    - Subprocess lifecycle management with crash detection
    - Automatic restart on crash (up to _MAX_RESTART_ATTEMPTS)
    - Port conflict resolution (kills stale processes)
    - SearXNG configuration via settings.yml
    - Graceful fallback to external SearXNG URL

    Uses an asyncio lock to prevent concurrent startup attempts.
    """
    global _searxng_process, _searxng_port, _restart_count, _last_restart_time

    if not settings.wet_auto_searxng:
        logger.info("Auto SearXNG disabled, using external URL")
        return settings.searxng_url

    # Serialize startup attempts to prevent concurrent starts
    async with _get_startup_lock():
        return await _ensure_searxng_locked()


async def _ensure_searxng_locked() -> str:
    """Inner ensure_searxng logic, called under lock."""
    global _restart_count

    # 1. Fast path: our own process is alive
    url = await _check_active_instance()
    if url:
        return url

    # 2. Try reusing existing SearXNG from another MCP server instance
    reused_url = await _try_reuse_existing()
    if reused_url:
        logger.info(f"Reusing existing SearXNG instance at {reused_url}")
        return reused_url

    # 3. Handle previous crash logging
    _handle_crashed_process()

    # 4. Check restart limits and apply cooldown
    if not await _check_restart_policy():
        return settings.searxng_url

    # 5. Ensure installed and start
    url = await _ensure_installation_and_start()
    if url:
        # Successful start — reset restart counter
        _restart_count = 0
        return url

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
