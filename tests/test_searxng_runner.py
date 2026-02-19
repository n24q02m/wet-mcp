from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from wet_mcp.searxng_runner import _get_settings_path, _wait_for_service


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
    mock_bundled_file.read_text.return_value = "server:\n  port: 8080\n"

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


@pytest.mark.asyncio
async def test_wait_for_service_success():
    with patch("wet_mcp.searxng_runner.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client_cls.return_value.__aenter__.return_value = mock_client
        mock_client_cls.return_value.__aexit__.return_value = None

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_client.get.return_value = mock_response

        # Mock sleep to run immediately
        with patch("wet_mcp.searxng_runner.asyncio.sleep", new_callable=AsyncMock):
            result = await _wait_for_service("http://localhost:8080")
            assert result is True


@pytest.mark.asyncio
async def test_wait_for_service_failure_retry():
    with patch("wet_mcp.searxng_runner.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client_cls.return_value.__aenter__.return_value = mock_client
        mock_client_cls.return_value.__aexit__.return_value = None

        # Fail with connection error, then succeed
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_client.get.side_effect = [
            httpx.ConnectError("Connection refused"),
            mock_response,
        ]

        # Mock sleep to verify it was called
        with patch(
            "wet_mcp.searxng_runner.asyncio.sleep", new_callable=AsyncMock
        ) as mock_sleep:
            result = await _wait_for_service("http://localhost:8080", timeout=5.0)
            assert result is True
            assert mock_sleep.call_count == 1
            assert mock_client.get.call_count == 2


@pytest.mark.asyncio
async def test_wait_for_service_timeout():
    with patch("wet_mcp.searxng_runner.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client_cls.return_value.__aenter__.return_value = mock_client
        mock_client_cls.return_value.__aexit__.return_value = None

        # Always fail with connection error
        mock_client.get.side_effect = httpx.ConnectError("Connection refused")

        # Mock sleep to verify calls
        with patch(
            "wet_mcp.searxng_runner.asyncio.sleep", new_callable=AsyncMock
        ) as mock_sleep:
            # Short timeout to avoid long test
            result = await _wait_for_service("http://localhost:8080", timeout=0.1)
            assert result is False
            assert mock_sleep.call_count > 0
