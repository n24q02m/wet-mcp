import asyncio
import signal
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
    _force_kill_process,
    _get_pip_command,
    _get_process_kwargs,
    _get_settings_path,
    _get_startup_lock,
    _install_searxng,
    _is_pid_alive,
    _is_searxng_installed,
    _kill_stale_port_process,
    _quick_health_check,
    _read_discovery,
    _remove_discovery,
    _start_searxng_subprocess,
    _try_reuse_existing,
    _wait_for_service,
    _write_discovery,
    ensure_searxng,
    stop_searxng,
)


# Need to reset global state before each test
@pytest.fixture(autouse=True)
def reset_globals():
    import wet_mcp.searxng_runner as module

    module._searxng_process = None
    module._searxng_port = None
    module._restart_count = 0
    module._last_restart_time = 0.0
    module._is_owner = False
    module._startup_lock = None
    yield
    module._searxng_process = None
    module._searxng_port = None
    module._restart_count = 0
    module._last_restart_time = 0.0
    module._is_owner = False
    module._startup_lock = None


def test_get_pip_command():
    with patch("shutil.which") as mock_which:
        # Case 1: uv is available
        mock_which.side_effect = lambda x: "/usr/bin/uv" if x == "uv" else None
        assert _get_pip_command() == [
            "/usr/bin/uv",
            "pip",
            "install",
            "--python",
            sys.executable,
        ]

        # Case 2: pip is available, uv is not
        mock_which.side_effect = lambda x: "/usr/bin/pip" if x == "pip" else None
        assert _get_pip_command() == ["/usr/bin/pip", "install"]

        # Case 3: neither is available
        mock_which.side_effect = None
        mock_which.return_value = None
        assert _get_pip_command() == [sys.executable, "-m", "pip", "install"]


def test_is_pid_alive_unix():
    with patch("sys.platform", "linux"), patch("os.kill") as mock_kill:
        # Alive
        mock_kill.return_value = None
        assert _is_pid_alive(1234) is True

        # Dead
        mock_kill.side_effect = ProcessLookupError()
        assert _is_pid_alive(1234) is False


def test_read_discovery(tmp_path):
    with patch(
        "wet_mcp.searxng_runner._DISCOVERY_FILE", tmp_path / "discovery.json"
    ) as mock_file:
        # File doesn't exist
        assert _read_discovery() is None

        # Invalid JSON
        mock_file.write_text("invalid")
        assert _read_discovery() is None

        # Valid JSON
        mock_file.write_text('{"pid": 1234, "port": 8080}')
        assert _read_discovery() == {"pid": 1234, "port": 8080}


def test_write_remove_discovery(tmp_path):
    file_path = tmp_path / "discovery.json"
    with patch("wet_mcp.searxng_runner._DISCOVERY_FILE", file_path):
        _write_discovery(8080, 1234)
        assert file_path.exists()
        import json

        data = json.loads(file_path.read_text())
        assert data["pid"] == 1234
        assert data["port"] == 8080

        _remove_discovery()
        assert not file_path.exists()


@pytest.mark.asyncio
async def test_quick_health_check():
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

        mock_client.get.side_effect = httpx.RequestError("error")
        assert await _quick_health_check("http://localhost:8080", retries=1) is False


@pytest.mark.asyncio
async def test_try_reuse_existing():
    with (
        patch("wet_mcp.searxng_runner._read_discovery") as mock_read,
        patch("wet_mcp.searxng_runner._is_pid_alive") as mock_alive,
        patch("wet_mcp.searxng_runner._quick_health_check") as mock_health,
    ):
        # Case 1: No discovery
        mock_read.return_value = None
        assert await _try_reuse_existing() is None

        # Case 2: Discovery but dead
        mock_read.return_value = {"pid": 1234, "port": 8080}
        mock_alive.return_value = False
        assert await _try_reuse_existing() is None

        # Case 3: Discovery, alive, healthy
        mock_alive.return_value = True
        mock_health.return_value = True
        assert await _try_reuse_existing() == "http://127.0.0.1:8080"

        # Case 4: Discovery, alive, unhealthy
        mock_health.return_value = False
        assert await _try_reuse_existing() is None


def test_find_available_port():
    with patch("socket.socket") as mock_socket:
        mock_sock_instance = MagicMock()
        mock_socket.return_value.__enter__.return_value = mock_sock_instance

        # Success on first try
        mock_sock_instance.bind.return_value = None
        port = _find_available_port(8080)
        assert 8080 <= port < 8080 + 50

        # Bind fails
        mock_sock_instance.bind.side_effect = OSError()
        port = _find_available_port(8080, max_tries=5)
        assert port == 8080  # Returns start_port on failure


@pytest.mark.asyncio
async def test_wait_for_service():
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_client = AsyncMock()
    mock_client.get.return_value = mock_response

    class MockClientContextManager:
        async def __aenter__(self):
            return mock_client

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass

    with patch("httpx.AsyncClient", return_value=MockClientContextManager()):
        assert await _wait_for_service("http://localhost:8080", timeout=1.0) is True


def test_is_searxng_installed():
    with patch("importlib.util.find_spec") as mock_find:
        mock_find.return_value = True
        assert _is_searxng_installed() is True

        mock_find.return_value = None
        assert _is_searxng_installed() is False


def test_install_searxng():
    with (
        patch("wet_mcp.searxng_runner._get_pip_command", return_value=["pip"]),
        patch("subprocess.run") as mock_run,
        patch("wet_mcp.searxng_runner.patch_searxng_version"),
        patch("wet_mcp.searxng_runner.patch_searxng_windows"),
    ):
        mock_run_result = MagicMock()
        mock_run_result.returncode = 0
        mock_run.return_value = mock_run_result

        assert _install_searxng() is True

        # Failure
        mock_run_result.returncode = 1
        assert _install_searxng() is False

        # Timeout
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="pip", timeout=1)
        assert _install_searxng() is False


def test_get_settings_path(tmp_path):
    with (
        patch("pathlib.Path.home", return_value=tmp_path),
        patch("importlib.resources.files") as mock_files,
    ):
        mock_files.return_value.joinpath.return_value.read_text.return_value = (
            "port: 41592\nsecret_key: 'REPLACE_WITH_REAL_SECRET'"
        )

        path = _get_settings_path(8080)
        assert path.exists()
        content = path.read_text()
        assert "port: 8080" in content
        assert "REPLACE_WITH_REAL_SECRET" not in content


def test_force_kill_process():
    proc = MagicMock(spec=subprocess.Popen)
    proc.poll.return_value = None
    proc.pid = 1234

    with (
        patch("sys.platform", "linux"),
        patch("os.killpg") as mock_killpg,
        patch("os.getpgid", return_value=1234),
    ):
        # Graceful
        _force_kill_process(proc)
        mock_killpg.assert_called_with(1234, signal.SIGTERM)
        proc.wait.assert_called_with(timeout=3)

        # Force kill
        proc.wait.side_effect = [subprocess.TimeoutExpired(cmd="test", timeout=3), None]
        _force_kill_process(proc)
        mock_killpg.assert_any_call(1234, signal.SIGKILL)


def test_kill_stale_port_process():
    with (
        patch("sys.platform", "linux"),
        patch("subprocess.run") as mock_run,
        patch("os.kill") as mock_kill,
    ):
        mock_run_result = MagicMock()
        mock_run_result.returncode = 0
        mock_run_result.stdout = "1234\n"
        mock_run.return_value = mock_run_result

        _kill_stale_port_process(8080)
        mock_kill.assert_called_with(1234, signal.SIGTERM)

    # Windows
    with (
        patch("sys.platform", "win32"),
        patch("subprocess.run") as mock_run,
        patch("os.kill") as mock_kill,
    ):
        mock_run_result = MagicMock()
        mock_run_result.stdout = "  TCP    127.0.0.1:8080         0.0.0.0:0              LISTENING       1234\n"
        mock_run.return_value = mock_run_result

        _kill_stale_port_process(8080)
        mock_kill.assert_called_with(1234, signal.SIGTERM)


def test_is_process_alive():
    import wet_mcp.searxng_runner as module

    # Process is None
    assert module._is_process_alive() is False

    # Process is alive
    proc = MagicMock()
    proc.poll.return_value = None
    module._searxng_process = proc
    assert module._is_process_alive() is True

    # Process is dead
    proc.poll.return_value = 1
    assert module._is_process_alive() is False


@pytest.mark.asyncio
async def test_start_searxng_subprocess():
    with (
        patch("wet_mcp.searxng_runner._find_available_port", return_value=8080),
        patch("wet_mcp.searxng_runner._kill_stale_port_process"),
        patch(
            "wet_mcp.searxng_runner._get_settings_path",
            return_value=Path("/tmp/settings.yml"),
        ),
        patch("subprocess.Popen") as mock_popen,
        patch("wet_mcp.searxng_runner._wait_for_service", return_value=True),
        patch("wet_mcp.searxng_runner._write_discovery"),
    ):
        mock_proc = MagicMock()
        mock_proc.pid = 1234
        mock_popen.return_value = mock_proc

        url = await _start_searxng_subprocess()
        assert url == "http://127.0.0.1:8080"

        import wet_mcp.searxng_runner as module

        assert module._searxng_process is mock_proc
        assert module._searxng_port == 8080
        assert module._is_owner is True


@pytest.mark.asyncio
async def test_start_searxng_subprocess_fail():
    with (
        patch("wet_mcp.searxng_runner._find_available_port", return_value=8080),
        patch("wet_mcp.searxng_runner._kill_stale_port_process"),
        patch(
            "wet_mcp.searxng_runner._get_settings_path",
            return_value=Path("/tmp/settings.yml"),
        ),
        patch("subprocess.Popen") as mock_popen,
        patch("wet_mcp.searxng_runner._wait_for_service", return_value=False),
        patch("wet_mcp.searxng_runner._force_kill_process"),
    ):
        mock_proc = MagicMock()
        mock_proc.poll.return_value = 1
        mock_popen.return_value = mock_proc

        url = await _start_searxng_subprocess()
        assert url is None


@pytest.mark.asyncio
async def test_start_searxng_subprocess_timeout_dead():
    with (
        patch("wet_mcp.searxng_runner._find_available_port", return_value=8080),
        patch("wet_mcp.searxng_runner._kill_stale_port_process"),
        patch(
            "wet_mcp.searxng_runner._get_settings_path",
            return_value=Path("/tmp/settings.yml"),
        ),
        patch("subprocess.Popen") as mock_popen,
        patch("wet_mcp.searxng_runner._wait_for_service", return_value=False),
        patch("wet_mcp.searxng_runner._force_kill_process"),
    ):
        mock_proc = MagicMock()
        mock_proc.poll.return_value = 1  # Dead
        mock_proc.stderr.read.return_value = b"stderr output"
        mock_popen.return_value = mock_proc

        url = await _start_searxng_subprocess()
        assert url is None


@pytest.mark.asyncio
async def test_start_searxng_subprocess_timeout_alive():
    with (
        patch("wet_mcp.searxng_runner._find_available_port", return_value=8080),
        patch("wet_mcp.searxng_runner._kill_stale_port_process"),
        patch(
            "wet_mcp.searxng_runner._get_settings_path",
            return_value=Path("/tmp/settings.yml"),
        ),
        patch("subprocess.Popen") as mock_popen,
        patch("wet_mcp.searxng_runner._wait_for_service", return_value=False),
        patch("wet_mcp.searxng_runner._force_kill_process") as mock_force_kill,
    ):
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None  # Alive
        mock_proc.pid = 999
        mock_popen.return_value = mock_proc

        url = await _start_searxng_subprocess()
        assert url is None
        mock_force_kill.assert_called_with(mock_proc)


@pytest.mark.asyncio
async def test_start_searxng_subprocess_exception():
    with patch(
        "wet_mcp.searxng_runner._find_available_port",
        side_effect=RuntimeError("Test error"),
    ):
        import wet_mcp.searxng_runner as module

        mock_proc = MagicMock()
        module._searxng_process = mock_proc

        with patch("wet_mcp.searxng_runner._force_kill_process") as mock_force_kill:
            url = await _start_searxng_subprocess()
            assert url is None

            # Since _start_searxng_subprocess kills existing processes BEFORE doing anything
            # it should have killed the mock_proc
            mock_force_kill.assert_called_with(mock_proc)
            assert module._searxng_process is None


@pytest.mark.asyncio
async def test_start_searxng_subprocess_exception_after_start():
    with (
        patch("wet_mcp.searxng_runner._find_available_port", return_value=8080),
        patch("wet_mcp.searxng_runner._kill_stale_port_process"),
        patch(
            "wet_mcp.searxng_runner._get_settings_path",
            return_value=Path("/tmp/settings.yml"),
        ),
        patch("subprocess.Popen") as mock_popen,
        patch(
            "wet_mcp.searxng_runner._wait_for_service",
            side_effect=RuntimeError("Test error"),
        ),
        patch("wet_mcp.searxng_runner._force_kill_process") as mock_force_kill,
    ):
        mock_proc = MagicMock()
        mock_proc.pid = 1234
        mock_popen.return_value = mock_proc

        import wet_mcp.searxng_runner as module

        url = await _start_searxng_subprocess()
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
    import wet_mcp.searxng_runner as module

    module._searxng_process = MagicMock()
    module._searxng_process.poll.return_value = None
    module._searxng_port = 8080

    with patch("wet_mcp.searxng_runner._quick_health_check", return_value=True):
        url = await _ensure_searxng_locked()
        assert url == "http://127.0.0.1:8080"


@pytest.mark.asyncio
async def test_ensure_searxng_locked_alive_but_unhealthy():
    import wet_mcp.searxng_runner as module

    mock_proc = MagicMock()
    mock_proc.poll.return_value = None
    module._searxng_process = mock_proc
    module._searxng_port = 8080

    with (
        patch("wet_mcp.searxng_runner._quick_health_check", return_value=False),
        patch("wet_mcp.searxng_runner._force_kill_process") as mock_force_kill,
        patch("wet_mcp.searxng_runner._try_reuse_existing", return_value=None),
        patch("wet_mcp.searxng_runner._is_searxng_installed", return_value=True),
        patch(
            "wet_mcp.searxng_runner._start_searxng_subprocess",
            return_value="http://127.0.0.1:8085",
        ),
    ):
        url = await _ensure_searxng_locked()
        assert url == "http://127.0.0.1:8085"

        # It should kill the unhealthy process
        mock_force_kill.assert_called_with(mock_proc)
        assert module._searxng_process is None


@pytest.mark.asyncio
async def test_ensure_searxng_locked_reuse_existing():
    with patch(
        "wet_mcp.searxng_runner._try_reuse_existing",
        return_value="http://127.0.0.1:8081",
    ):
        url = await _ensure_searxng_locked()
        assert url == "http://127.0.0.1:8081"


@pytest.mark.asyncio
async def test_ensure_searxng_locked_start():
    with (
        patch("wet_mcp.searxng_runner._try_reuse_existing", return_value=None),
        patch("wet_mcp.searxng_runner._is_searxng_installed", return_value=True),
        patch(
            "wet_mcp.searxng_runner._start_searxng_subprocess",
            return_value="http://127.0.0.1:8082",
        ),
    ):
        url = await _ensure_searxng_locked()
        assert url == "http://127.0.0.1:8082"


@pytest.mark.asyncio
async def test_ensure_searxng_locked_max_restarts():
    import wet_mcp.searxng_runner as module

    module._restart_count = 3
    module._last_restart_time = 0.0

    with (
        patch("wet_mcp.searxng_runner._try_reuse_existing", return_value=None),
        patch("time.time", return_value=1.0),
    ):
        url = await _ensure_searxng_locked()
        assert url == settings.searxng_url


@pytest.mark.asyncio
async def test_ensure_searxng_locked_crash_cleanup():
    import wet_mcp.searxng_runner as module

    module._searxng_process = MagicMock()
    module._searxng_process.poll.return_value = 1
    module._searxng_process.stderr.read.return_value = b"error message"
    module._searxng_port = 8080

    with (
        patch("wet_mcp.searxng_runner._try_reuse_existing", return_value=None),
        patch("wet_mcp.searxng_runner._is_searxng_installed", return_value=True),
        patch(
            "wet_mcp.searxng_runner._start_searxng_subprocess",
            return_value="http://127.0.0.1:8083",
        ),
    ):
        url = await _ensure_searxng_locked()
        assert url == "http://127.0.0.1:8083"


@pytest.mark.asyncio
async def test_ensure_searxng_locked_install_fails():
    with (
        patch("wet_mcp.searxng_runner._try_reuse_existing", return_value=None),
        patch("wet_mcp.searxng_runner._is_searxng_installed", return_value=False),
        patch("wet_mcp.searxng_runner._install_searxng", return_value=False),
    ):
        url = await _ensure_searxng_locked()
        assert url == settings.searxng_url


def test_get_startup_lock():

    lock1 = _get_startup_lock()
    lock2 = _get_startup_lock()
    assert lock1 is lock2
    assert isinstance(lock1, asyncio.Lock)


def test_cleanup_process():

    import wet_mcp.searxng_runner as module

    mock_proc = MagicMock()
    module._searxng_process = mock_proc
    module._is_owner = True
    module._searxng_port = 8080

    with (
        patch("wet_mcp.searxng_runner._force_kill_process") as mock_kill,
        patch("wet_mcp.searxng_runner._remove_discovery") as mock_remove,
    ):
        stop_searxng()

        mock_kill.assert_called_with(mock_proc)
        mock_remove.assert_called_once()

        assert module._searxng_process is None
        assert module._searxng_port is None
        assert module._is_owner is False


def test_cleanup_process_not_owner():
    import wet_mcp.searxng_runner as module

    mock_proc = MagicMock()
    module._searxng_process = mock_proc
    module._is_owner = False

    with (
        patch("wet_mcp.searxng_runner._force_kill_process") as mock_kill,
        patch("wet_mcp.searxng_runner._remove_discovery") as mock_remove,
    ):
        _cleanup_process()

        mock_kill.assert_not_called()
        mock_remove.assert_not_called()


def test_get_process_kwargs():
    with patch("sys.platform", "linux"):
        kwargs = _get_process_kwargs()
        assert "preexec_fn" in kwargs

    with patch("sys.platform", "win32"):
        if not hasattr(subprocess, "CREATE_NEW_PROCESS_GROUP"):
            subprocess.CREATE_NEW_PROCESS_GROUP = 512
        kwargs = _get_process_kwargs()
        assert "creationflags" in kwargs
