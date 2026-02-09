"""Embedded SearXNG process management.

Replaces Docker-based SearXNG with a subprocess running directly from
the installed SearXNG Python package. SearXNG is auto-installed from
GitHub on first run if not already available.

On Windows, valkeydb.py is patched to remove Unix-only ``pwd`` dependency.
"""

import asyncio
import atexit
import os
import socket
import subprocess
import sys
from importlib.resources import files
from pathlib import Path

import httpx
from loguru import logger

from wet_mcp.config import settings
from wet_mcp.setup import patch_searxng_version

# SearXNG install URL (zip archive avoids git filename issues on Windows)
_SEARXNG_INSTALL_URL = (
    "https://github.com/searxng/searxng/archive/refs/heads/master.zip"
)

# Module-level process reference for cleanup
_searxng_process: subprocess.Popen | None = None
_searxng_port: int | None = None


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


async def _wait_for_service(url: str, timeout: float = 60.0) -> bool:
    """Wait for SearXNG service to be healthy via async HTTP check."""
    import time

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
                    timeout=2.0,
                )
                if response.status_code == 200:
                    return True
            except Exception:
                pass
            await asyncio.sleep(1.0)
    return False


def _is_searxng_installed() -> bool:
    """Check if the SearXNG Python package is installed."""
    try:
        import searx  # noqa: F401

        return True
    except ImportError:
        return False


def _install_searxng() -> bool:
    """Install SearXNG from GitHub zip archive.

    Uses zip URL instead of git+ to avoid filename issues on some
    platforms. Pre-installs build dependencies before SearXNG.

    Returns:
        True if installation succeeded.
    """
    logger.info("Installing SearXNG from GitHub (first run)...")

    try:
        # Pre-install build dependencies required by SearXNG
        logger.debug("Installing SearXNG build dependencies...")
        deps_result = subprocess.run(
            [
                sys.executable,
                "-m",
                "pip",
                "install",
                "--quiet",
                "msgspec",
                "setuptools",
                "wheel",
                "pyyaml",
            ],
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
                sys.executable,
                "-m",
                "pip",
                "install",
                "--quiet",
                "--no-build-isolation",
                _SEARXNG_INSTALL_URL,
            ],
            capture_output=True,
            text=True,
            timeout=300,
        )

        if result.returncode == 0:
            logger.info("SearXNG installed successfully")
            patch_searxng_version()
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
        "port: 8080",
        f"port: {port}",
    )

    settings_file.write_text(content)
    logger.debug(f"SearXNG settings written to: {settings_file}")

    return settings_file


def _cleanup_process() -> None:
    """Cleanup SearXNG subprocess and per-process settings file on exit."""
    global _searxng_process, _searxng_port
    if _searxng_process is not None:
        try:
            logger.debug("Stopping SearXNG subprocess...")
            _searxng_process.terminate()
            try:
                _searxng_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                _searxng_process.kill()
                _searxng_process.wait(timeout=3)
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


async def ensure_searxng() -> str:
    """Start embedded SearXNG subprocess if not running. Returns URL.

    This function handles:
    - Auto-installation of SearXNG package from GitHub on first run
    - Subprocess lifecycle management
    - Port conflict resolution
    - SearXNG configuration via settings.yml
    - Graceful fallback to external SearXNG URL
    """
    global _searxng_process, _searxng_port

    if not settings.wet_auto_searxng:
        logger.info("Auto SearXNG disabled, using external URL")
        return settings.searxng_url

    # Check if SearXNG is already running (from previous call)
    if _searxng_process is not None and _searxng_process.poll() is None:
        url = f"http://127.0.0.1:{_searxng_port}"
        logger.debug(f"SearXNG already running at {url}")
        return url

    # Ensure SearXNG is installed
    if not _is_searxng_installed():
        if not _install_searxng():
            logger.warning("SearXNG installation failed, using external URL")
            return settings.searxng_url

    try:
        # Find available port
        port = await asyncio.to_thread(_find_available_port, settings.wet_searxng_port)
        if port != settings.wet_searxng_port:
            logger.info(f"Port {settings.wet_searxng_port} in use, using {port}")
        _searxng_port = port

        # Write settings with correct port
        settings_path = _get_settings_path(port)

        # Build environment for SearXNG
        env = os.environ.copy()
        env["SEARXNG_SETTINGS_PATH"] = str(settings_path)

        # Start SearXNG subprocess
        logger.info(f"Starting SearXNG on port {port}...")

        _searxng_process = await asyncio.to_thread(
            lambda: subprocess.Popen(
                [sys.executable, "-m", "wet_mcp.searxng_wrapper"],
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                # Use process group on Unix for clean shutdown
                **(_get_process_kwargs()),
            )
        )

        # Register cleanup
        atexit.register(_cleanup_process)

        url = f"http://127.0.0.1:{port}"

        # Wait for SearXNG to be healthy
        if await _wait_for_service(url, timeout=60.0):
            logger.info(f"SearXNG ready at {url}")
        else:
            logger.warning(f"SearXNG started but not healthy at {url}")
            # Check if process crashed
            if _searxng_process.poll() is not None:
                stderr = (
                    _searxng_process.stderr.read().decode()
                    if _searxng_process.stderr
                    else ""
                )
                logger.error(f"SearXNG process exited: {stderr[:500]}")
                _searxng_process = None
                return settings.searxng_url

        return url

    except Exception as e:
        logger.error(f"Failed to start SearXNG: {e}")
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
