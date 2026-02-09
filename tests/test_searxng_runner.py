from pathlib import Path
from unittest.mock import MagicMock, patch

from wet_mcp.searxng_runner import _get_settings_path


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
        # We can verify that the division happened with the expected string
        mock_home.__truediv__.assert_called_with(".wet-mcp")
        mock_config_dir.__truediv__.assert_called_with("searxng_settings_12345.yml")

        # Verify read_text called
        mock_bundled_file.read_text.assert_called_once()

        # Verify write_text called with correct content
        expected_content = "server:\n  port: 9090\n"
        mock_settings_file.write_text.assert_called_once_with(expected_content)
