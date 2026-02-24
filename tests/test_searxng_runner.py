from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from wet_mcp import searxng_runner
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


@pytest.fixture
def mock_startup_lock():
    lock = AsyncMock()
    lock.__aenter__.return_value = None
    lock.__aexit__.return_value = None
    return lock


@pytest.mark.asyncio
async def test_ensure_searxng_fast_path(mock_startup_lock):
    """Test fast path: already running and healthy."""
    with (
        patch(
            "wet_mcp.searxng_runner._get_startup_lock", return_value=mock_startup_lock
        ),
        patch("wet_mcp.searxng_runner._is_process_alive", return_value=True),
        patch(
            "wet_mcp.searxng_runner._quick_health_check", new_callable=AsyncMock
        ) as mock_health,
        patch("wet_mcp.searxng_runner.settings") as mock_settings,
    ):
        mock_settings.wet_auto_searxng = True
        mock_health.return_value = True

        searxng_runner._searxng_port = 8080
        searxng_runner._searxng_process = MagicMock()

        url = await ensure_searxng()
        assert url == "http://127.0.0.1:8080"


@pytest.mark.asyncio
async def test_ensure_searxng_restart(mock_startup_lock):
    """Test restart flow: not running, installs, starts."""
    with (
        patch(
            "wet_mcp.searxng_runner._get_startup_lock", return_value=mock_startup_lock
        ),
        patch("wet_mcp.searxng_runner._is_process_alive", return_value=False),
        patch(
            "wet_mcp.searxng_runner._try_reuse_existing", new_callable=AsyncMock
        ) as mock_reuse,
        patch("wet_mcp.searxng_runner._is_searxng_installed", return_value=False),
        patch("wet_mcp.searxng_runner._install_searxng", return_value=True),
        patch(
            "wet_mcp.searxng_runner._start_searxng_subprocess", new_callable=AsyncMock
        ) as mock_start,
        patch("wet_mcp.searxng_runner.settings") as mock_settings,
    ):
        mock_settings.wet_auto_searxng = True
        mock_reuse.return_value = None
        mock_start.return_value = "http://127.0.0.1:9090"

        # Reset globals
        searxng_runner._searxng_process = None
        searxng_runner._searxng_port = None
        searxng_runner._restart_count = 0

        url = await ensure_searxng()
        assert url == "http://127.0.0.1:9090"
        assert searxng_runner._restart_count == 0


@pytest.mark.asyncio
async def test_ensure_searxng_crash_recovery(mock_startup_lock):
    """Test crash recovery: process exists but dead, restarts."""
    mock_process = MagicMock()
    mock_process.poll.return_value = 1  # Crashed
    mock_process.stderr.read.return_value = b"error"

    with (
        patch(
            "wet_mcp.searxng_runner._get_startup_lock", return_value=mock_startup_lock
        ),
        patch("wet_mcp.searxng_runner._is_process_alive", return_value=False),
        patch(
            "wet_mcp.searxng_runner._try_reuse_existing", new_callable=AsyncMock
        ) as mock_reuse,
        patch("wet_mcp.searxng_runner._is_searxng_installed", return_value=True),
        patch(
            "wet_mcp.searxng_runner._start_searxng_subprocess", new_callable=AsyncMock
        ) as mock_start,
        patch("wet_mcp.searxng_runner.settings") as mock_settings,
    ):
        mock_settings.wet_auto_searxng = True
        mock_reuse.return_value = None
        mock_start.return_value = "http://127.0.0.1:9090"

        searxng_runner._searxng_process = mock_process
        searxng_runner._searxng_port = 8080
        searxng_runner._restart_count = 0

        url = await ensure_searxng()
        assert url == "http://127.0.0.1:9090"
