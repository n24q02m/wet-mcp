from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from wet_mcp.searxng_runner import _get_settings_path, ensure_searxng


def test_get_settings_path():
    # Mock Path.home()
    mock_home = MagicMock(spec=Path)

    # Mock file operations
    mock_config_dir = MagicMock(spec=Path)
    mock_settings_file = MagicMock(spec=Path)

    # Chain the mocks: Path.home() / ".wet-mcp" -> mock_config_dir
    mock_home.__truediv__.return_value = mock_config_dir

    # Chain the mocks: mock_config_dir / filename -> mock_settings_file
    mock_config_dir.__truediv__.return_value = mock_settings_file

    # Mock files("wet_mcp")
    mock_files = MagicMock()
    mock_bundled_file = MagicMock()
    mock_files.joinpath.return_value = mock_bundled_file
    mock_bundled_file.read_text.return_value = "server:\n  port: 41592\n"

    with (
        patch("wet_mcp.searxng_runner.Path") as mock_path_cls,
        patch("wet_mcp.searxng_runner.os.getpid") as mock_getpid,
        patch("wet_mcp.searxng_runner.files", return_value=mock_files),
    ):
        # Setup mock returns
        mock_path_cls.home.return_value = mock_home
        mock_getpid.return_value = 12345

        # Call the function
        port = 9090
        result = _get_settings_path(port)

        # Verify result
        assert result == mock_settings_file

        # Verify mkdir called
        mock_config_dir.mkdir.assert_called_once_with(parents=True, exist_ok=True)

        # Verify file path construction
        mock_home.__truediv__.assert_called_with(".wet-mcp")
        mock_config_dir.__truediv__.assert_called_with("searxng_settings_12345.yml")

        # Verify read_text called
        mock_bundled_file.read_text.assert_called_once()

        # Verify write_text called with correct content
        expected_content = "server:\n  port: 9090\n"
        mock_settings_file.write_text.assert_called_once_with(expected_content)

# Mock the settings object
@pytest.fixture
def mock_settings():
    with patch("wet_mcp.searxng_runner.settings") as mock:
        mock.wet_auto_searxng = True
        mock.searxng_url = "http://external:8080"
        mock.wet_searxng_port = 8080
        yield mock

# Mock the lock
@pytest.fixture
def mock_lock():
    lock = AsyncMock()
    lock.__aenter__.return_value = None
    lock.__aexit__.return_value = None
    with patch("wet_mcp.searxng_runner._get_startup_lock", return_value=lock):
        yield lock

# Mock time
@pytest.fixture
def mock_time():
    with patch("wet_mcp.searxng_runner.time") as mock:
        mock.time.return_value = 1000.0
        yield mock

# Mock asyncio.sleep
@pytest.fixture
def mock_sleep():
    with patch("wet_mcp.searxng_runner.asyncio.sleep", new_callable=AsyncMock) as mock:
        yield mock

@pytest.mark.asyncio
async def test_ensure_searxng_auto_disabled(mock_settings, mock_lock):
    """Test ensure_searxng returns external URL when auto-start is disabled."""
    mock_settings.wet_auto_searxng = False

    url = await ensure_searxng()

    assert url == "http://external:8080"
    mock_lock.__aenter__.assert_not_called()

@pytest.mark.asyncio
async def test_ensure_searxng_already_running_healthy(mock_settings, mock_lock):
    """Test ensure_searxng returns localhost URL when process is already running and healthy."""
    with patch("wet_mcp.searxng_runner._is_process_alive", return_value=True),          patch("wet_mcp.searxng_runner._searxng_port", 8080),          patch("wet_mcp.searxng_runner._searxng_process", MagicMock()),          patch("wet_mcp.searxng_runner._quick_health_check", new_callable=AsyncMock) as mock_health:

        mock_health.return_value = True

        url = await ensure_searxng()

        assert url == "http://127.0.0.1:8080"
        mock_health.assert_called_once_with("http://127.0.0.1:8080", retries=1)

@pytest.mark.asyncio
async def test_ensure_searxng_already_running_unhealthy(mock_settings, mock_lock, mock_time):
    """Test ensure_searxng kills unhealthy process and restarts."""
    mock_process = MagicMock()
    mock_process.pid = 12345

    with patch("wet_mcp.searxng_runner._is_process_alive", return_value=True),          patch("wet_mcp.searxng_runner._searxng_port", 8080),          patch("wet_mcp.searxng_runner._searxng_process", mock_process),          patch("wet_mcp.searxng_runner._quick_health_check", new_callable=AsyncMock) as mock_health,          patch("wet_mcp.searxng_runner._force_kill_process") as mock_kill,          patch("wet_mcp.searxng_runner._try_reuse_existing", new_callable=AsyncMock) as mock_reuse,          patch("wet_mcp.searxng_runner._is_searxng_installed", return_value=True),          patch("wet_mcp.searxng_runner._start_searxng_subprocess", new_callable=AsyncMock) as mock_start:

        mock_health.return_value = False
        mock_reuse.return_value = None
        mock_start.return_value = "http://127.0.0.1:9090"

        # We need to handle the global variable update flow.
        # The function reads globals at start.
        # Then it kills process and sets globals to None.
        # Then it proceeds to start new process.

        url = await ensure_searxng()

        assert url == "http://127.0.0.1:9090"
        mock_kill.assert_called_once_with(mock_process)
        mock_start.assert_called_once()

@pytest.mark.asyncio
async def test_ensure_searxng_reuse_existing(mock_settings, mock_lock):
    """Test ensure_searxng reuses existing shared instance."""
    with patch("wet_mcp.searxng_runner._is_process_alive", return_value=False),          patch("wet_mcp.searxng_runner._try_reuse_existing", new_callable=AsyncMock) as mock_reuse:

        mock_reuse.return_value = "http://127.0.0.1:7777"

        url = await ensure_searxng()

        assert url == "http://127.0.0.1:7777"

@pytest.mark.asyncio
async def test_ensure_searxng_restart_limit(mock_settings, mock_lock, mock_time):
    """Test ensure_searxng gives up after max restarts."""
    # Simulate restart count >= limit (limit is 3)
    # _MAX_RESTART_ATTEMPTS is 3

    with patch("wet_mcp.searxng_runner._is_process_alive", return_value=False),          patch("wet_mcp.searxng_runner._try_reuse_existing", new_callable=AsyncMock) as mock_reuse,          patch("wet_mcp.searxng_runner._restart_count", 3),          patch("wet_mcp.searxng_runner._last_restart_time", 1000.0):

        mock_reuse.return_value = None

        url = await ensure_searxng()

        assert url == "http://external:8080"

@pytest.mark.asyncio
async def test_ensure_searxng_install_fail(mock_settings, mock_lock, mock_time):
    """Test ensure_searxng falls back if installation fails."""
    with patch("wet_mcp.searxng_runner._is_process_alive", return_value=False),          patch("wet_mcp.searxng_runner._try_reuse_existing", new_callable=AsyncMock) as mock_reuse,          patch("wet_mcp.searxng_runner._restart_count", 0),          patch("wet_mcp.searxng_runner._is_searxng_installed", return_value=False),          patch("wet_mcp.searxng_runner._install_searxng", return_value=False) as mock_install:

        mock_reuse.return_value = None

        url = await ensure_searxng()

        assert url == "http://external:8080"
        mock_install.assert_called_once()

@pytest.mark.asyncio
async def test_ensure_searxng_start_success(mock_settings, mock_lock, mock_time, mock_sleep):
    """Test ensure_searxng successfully starts new process."""
    with patch("wet_mcp.searxng_runner._is_process_alive", return_value=False),          patch("wet_mcp.searxng_runner._try_reuse_existing", new_callable=AsyncMock) as mock_reuse,          patch("wet_mcp.searxng_runner._restart_count", 1),          patch("wet_mcp.searxng_runner._last_restart_time", 1000.0),          patch("wet_mcp.searxng_runner._is_searxng_installed", return_value=True),          patch("wet_mcp.searxng_runner._start_searxng_subprocess", new_callable=AsyncMock) as mock_start:

        mock_reuse.return_value = None
        mock_start.return_value = "http://127.0.0.1:5555"

        url = await ensure_searxng()

        assert url == "http://127.0.0.1:5555"
        # Should invoke cooldown sleep since restart_count > 0
        mock_sleep.assert_called_once()

@pytest.mark.asyncio
async def test_ensure_searxng_start_fail(mock_settings, mock_lock, mock_time):
    """Test ensure_searxng falls back if start fails."""
    with patch("wet_mcp.searxng_runner._is_process_alive", return_value=False),          patch("wet_mcp.searxng_runner._try_reuse_existing", new_callable=AsyncMock) as mock_reuse,          patch("wet_mcp.searxng_runner._restart_count", 0),          patch("wet_mcp.searxng_runner._is_searxng_installed", return_value=True),          patch("wet_mcp.searxng_runner._start_searxng_subprocess", new_callable=AsyncMock) as mock_start:

        mock_reuse.return_value = None
        mock_start.return_value = None

        url = await ensure_searxng()

        assert url == "http://external:8080"
