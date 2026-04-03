import asyncio
import subprocess
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from wet_mcp.config import settings
from wet_mcp.searxng_runner import (
    _cleanup_process,
    _ensure_searxng_locked,
    _find_available_port,
    _get_process_kwargs,
    _get_startup_lock,
    _health_cache,
    _is_pid_alive,
    _quick_health_check,
    _start_searxng_subprocess,
    ensure_searxng,
    stop_searxng,
)


@pytest.mark.asyncio
async def test_ensure_searxng():
    with patch(
        "web_core.search.runner.ensure_searxng",
        return_value="http://127.0.0.1:8080",
    ) as mock_ensure:
        url = await ensure_searxng()
        assert url == "http://127.0.0.1:8080"
        mock_ensure.assert_called_once()


@pytest.mark.asyncio
async def test_ensure_searxng_fail():
    with patch(
        "web_core.search.runner.ensure_searxng",
        side_effect=RuntimeError("Test error"),
    ):
        url = await ensure_searxng()
        assert url == settings.searxng_url


def test_stop_searxng():
    with patch("wet_mcp.searxng_runner.shutdown_searxng") as mock_shutdown:
        stop_searxng()
        mock_shutdown.assert_called_once()


@pytest.mark.asyncio
async def test_quick_health_check():
    _health_cache.clear()
    mock_response = MagicMock()
    mock_response.status_code = 200

    mock_client = AsyncMock()
    mock_client.get.return_value = mock_response

    # Need to patch httpx.AsyncClient context manager
    class MockClientContextManager:
        async def __aenter__(self):
            return mock_client

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass

    with patch("httpx.AsyncClient", return_value=MockClientContextManager()):
        assert await _quick_health_check("http://localhost:8080", retries=1) is True

        # Clear cache to force a new check
        _health_cache.clear()
        mock_client.get.side_effect = httpx.RequestError("error")
        assert await _quick_health_check("http://localhost:8080", retries=1) is False


def test_is_pid_alive():
    with patch("os.kill") as mock_kill:
        mock_kill.return_value = None
        assert _is_pid_alive(1234) is True

        mock_kill.side_effect = OSError()
        assert _is_pid_alive(1234) is False


def test_find_available_port():
    with patch("socket.socket") as mock_socket:
        mock_sock_instance = MagicMock()
        mock_socket.return_value.__enter__.return_value = mock_sock_instance

        # Success on first try
        mock_sock_instance.bind.return_value = None
        port = _find_available_port(8080)
        assert 8080 <= port < 8080 + 100

        # Bind fails
        mock_sock_instance.bind.side_effect = OSError()
        with pytest.raises(RuntimeError, match="No available port found"):
            _find_available_port(8080, max_tries=1)


@pytest.mark.asyncio
async def test_start_searxng_subprocess_success():
    with (
        patch("web_core.search.runner._find_available_port", return_value=8080),
        patch("web_core.search.runner._kill_stale_port_process"),
        patch(
            "web_core.search.runner._get_settings_path",
            return_value=Path("/tmp/settings.yml"),
        ),
        patch("subprocess.Popen") as mock_popen,
        patch("web_core.search.runner._wait_for_service", return_value=True),
        patch("web_core.search.runner._write_discovery"),
    ):
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None  # Alive
        mock_proc.pid = 1234
        mock_popen.return_value = mock_proc

        url = await _start_searxng_subprocess(8080)
        assert url == "http://127.0.0.1:8080"


@pytest.mark.asyncio
async def test_start_searxng_subprocess_timeout_dead():
    with (
        patch("web_core.search.runner._find_available_port", return_value=8080),
        patch("web_core.search.runner._kill_stale_port_process"),
        patch(
            "web_core.search.runner._get_settings_path",
            return_value=Path("/tmp/settings.yml"),
        ),
        patch("subprocess.Popen") as mock_popen,
        patch("web_core.search.runner._wait_for_service", return_value=False),
        patch("web_core.search.runner._force_kill_process"),
    ):
        mock_proc = MagicMock()
        mock_proc.poll.return_value = 1  # Dead
        mock_proc.stderr.read.return_value = b"stderr output"
        mock_popen.return_value = mock_proc

        url = await _start_searxng_subprocess(8080)
        assert url is None


@pytest.mark.asyncio
async def test_start_searxng_subprocess_timeout_alive():
    with (
        patch("web_core.search.runner._find_available_port", return_value=8080),
        patch("web_core.search.runner._kill_stale_port_process"),
        patch(
            "web_core.search.runner._get_settings_path",
            return_value=Path("/tmp/settings.yml"),
        ),
        patch("subprocess.Popen") as mock_popen,
        patch("web_core.search.runner._wait_for_service", return_value=False),
        patch("web_core.search.runner._force_kill_process") as mock_force_kill,
    ):
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None  # Alive
        mock_proc.pid = 999
        mock_popen.return_value = mock_proc

        url = await _start_searxng_subprocess(8080)
        assert url is None
        mock_force_kill.assert_called_with(mock_proc)


@pytest.mark.asyncio
async def test_start_searxng_subprocess_exception():
    with patch(
        "web_core.search.runner._find_available_port",
        side_effect=RuntimeError("Test error"),
    ):
        import web_core.search.runner as module

        mock_proc = MagicMock()
        module._searxng_process = mock_proc

        with patch("web_core.search.runner._force_kill_process") as mock_force_kill:
            url = await _start_searxng_subprocess(8080)
            assert url is None

            # Since _start_searxng_subprocess kills existing processes BEFORE doing anything
            # it should have killed the mock_proc
            mock_force_kill.assert_called_with(mock_proc)
            assert module._searxng_process is None


@pytest.mark.asyncio
async def test_start_searxng_subprocess_exception_after_start():
    with (
        patch("web_core.search.runner._find_available_port", return_value=8080),
        patch("web_core.search.runner._kill_stale_port_process"),
        patch(
            "web_core.search.runner._get_settings_path",
            return_value=Path("/tmp/settings.yml"),
        ),
        patch("subprocess.Popen") as mock_popen,
        patch(
            "web_core.search.runner._wait_for_service",
            side_effect=RuntimeError("Test error"),
        ),
        patch("web_core.search.runner._force_kill_process") as mock_force_kill,
    ):
        mock_proc = MagicMock()
        mock_proc.pid = 1234
        mock_popen.return_value = mock_proc

        import web_core.search.runner as module

        url = await _start_searxng_subprocess(8080)
        assert url is None

        # It should kill the newly created process because of the exception
        mock_force_kill.assert_called_with(mock_proc)
        assert module._searxng_process is None


@pytest.mark.asyncio
async def test_ensure_searxng_disabled():
    with patch("wet_mcp.config.settings.wet_auto_searxng", False):
        url = await ensure_searxng()
        assert url == settings.searxng_url


@pytest.mark.asyncio
async def test_ensure_searxng_locked_reuse():
    import web_core.search.runner as module

    module._searxng_process = MagicMock()
    module._searxng_process.poll.return_value = None
    module._searxng_port = 8080

    with patch("web_core.search.runner._quick_health_check", return_value=True):
        url = await _ensure_searxng_locked(auto_start=True, start_port=8080)
        assert url == "http://127.0.0.1:8080"


@pytest.mark.asyncio
async def test_ensure_searxng_locked_alive_but_unhealthy():
    import web_core.search.runner as module

    mock_proc = MagicMock()
    mock_proc.poll.return_value = None
    module._searxng_process = mock_proc
    module._searxng_port = 8080

    with (
        patch("web_core.search.runner._quick_health_check", return_value=False),
        patch("web_core.search.runner._force_kill_process") as mock_force_kill,
        patch("web_core.search.runner._try_reuse_existing", return_value=None),
        patch("web_core.search.runner._is_searxng_installed", return_value=True),
        patch(
            "web_core.search.runner._start_searxng_subprocess",
            return_value="http://127.0.0.1:8085",
        ),
    ):
        url = await _ensure_searxng_locked(auto_start=True, start_port=8080)
        assert url == "http://127.0.0.1:8085"

        # It should kill the unhealthy process
        mock_force_kill.assert_called_with(mock_proc)
        assert module._searxng_process is None


@pytest.mark.asyncio
async def test_ensure_searxng_locked_reuse_existing():
    with patch(
        "web_core.search.runner._try_reuse_existing",
        return_value="http://127.0.0.1:8081",
    ):
        url = await _ensure_searxng_locked(auto_start=True, start_port=8080)
        assert url == "http://127.0.0.1:8081"


@pytest.mark.asyncio
async def test_ensure_searxng_locked_start():
    with (
        patch("web_core.search.runner._try_reuse_existing", return_value=None),
        patch("web_core.search.runner._is_searxng_installed", return_value=True),
        patch(
            "web_core.search.runner._start_searxng_subprocess",
            return_value="http://127.0.0.1:8082",
        ),
    ):
        url = await _ensure_searxng_locked(auto_start=True, start_port=8080)
        assert url == "http://127.0.0.1:8082"


@pytest.mark.asyncio
async def test_ensure_searxng_locked_max_restarts():
    import web_core.search.runner as module

    module._restart_count = 3
    module._last_restart_time = 0.0

    with (
        patch("web_core.search.runner._try_reuse_existing", return_value=None),
        patch("time.time", return_value=1.0),
    ):
        with pytest.raises(RuntimeError, match="restart limit reached"):
            await _ensure_searxng_locked(auto_start=True, start_port=8080)


@pytest.mark.asyncio
async def test_ensure_searxng_locked_crash_cleanup():
    import web_core.search.runner as module

    module._searxng_process = MagicMock()
    module._searxng_process.poll.return_value = 1
    module._searxng_process.stderr.read.return_value = b"error message"
    module._searxng_port = 8080

    with (
        patch("web_core.search.runner._try_reuse_existing", return_value=None),
        patch("web_core.search.runner._is_searxng_installed", return_value=True),
        patch(
            "web_core.search.runner._start_searxng_subprocess",
            return_value="http://127.0.0.1:8083",
        ),
    ):
        url = await _ensure_searxng_locked(auto_start=True, start_port=8080)
        assert url == "http://127.0.0.1:8083"


@pytest.mark.asyncio
async def test_ensure_searxng_locked_install_fails():
    with (
        patch("web_core.search.runner._try_reuse_existing", return_value=None),
        patch("web_core.search.runner._is_searxng_installed", return_value=False),
        patch("web_core.search.runner._install_searxng", return_value=False),
    ):
        with pytest.raises(RuntimeError, match="installation failed"):
            await _ensure_searxng_locked(auto_start=True, start_port=8080)


def test_get_startup_lock():
    lock1 = _get_startup_lock()
    lock2 = _get_startup_lock()
    assert lock1 is lock2
    assert isinstance(lock1, asyncio.Lock)


def test_cleanup_process():
    import web_core.search.runner as module

    mock_proc = MagicMock()
    module._searxng_process = mock_proc
    module._is_owner = True
    module._searxng_port = 8080

    with (
        patch("web_core.search.runner._force_kill_process") as mock_kill,
        patch("web_core.search.runner._remove_discovery") as mock_remove,
    ):
        stop_searxng()

        mock_kill.assert_called_with(mock_proc)
        mock_remove.assert_called_once()

        assert module._searxng_process is None
        assert module._searxng_port is None
        assert module._is_owner is False


def test_cleanup_process_not_owner():
    import web_core.search.runner as module

    mock_proc = MagicMock()
    module._searxng_process = mock_proc
    module._is_owner = False

    with (
        patch("web_core.search.runner._force_kill_process") as mock_kill,
        patch("web_core.search.runner._remove_discovery") as mock_remove,
    ):
        _cleanup_process()

        mock_kill.assert_not_called()
        mock_remove.assert_not_called()


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="Unix-only: os.setsid not available on Windows",
)
def test_get_process_kwargs_unix():
    with patch("sys.platform", "linux"):
        kwargs = _get_process_kwargs()
        assert "preexec_fn" in kwargs


def test_get_process_kwargs_win32():
    with patch("sys.platform", "win32"):
        if not hasattr(subprocess, "CREATE_NEW_PROCESS_GROUP"):
            subprocess.CREATE_NEW_PROCESS_GROUP = 512
        kwargs = _get_process_kwargs()
        assert "creationflags" in kwargs
