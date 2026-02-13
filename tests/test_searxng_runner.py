from pathlib import Path
from unittest.mock import MagicMock, patch

from wet_mcp.searxng_runner import _find_available_port, _get_settings_path


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


def test_find_available_port_success():
    """Test finding an available port on the first try."""
    with patch("wet_mcp.searxng_runner.socket.socket") as mock_socket_cls:
        mock_socket = mock_socket_cls.return_value
        mock_socket.__enter__.return_value = mock_socket

        # Simulate successful bind
        mock_socket.bind.return_value = None

        start_port = 8080
        port = _find_available_port(start_port)

        assert port == start_port
        mock_socket.bind.assert_called_once_with(("127.0.0.1", start_port))


def test_find_available_port_retry():
    """Test finding an available port after retries."""
    with patch("wet_mcp.searxng_runner.socket.socket") as mock_socket_cls:
        mock_socket = mock_socket_cls.return_value
        mock_socket.__enter__.return_value = mock_socket

        # Simulate bind failure on first call, success on second
        mock_socket.bind.side_effect = [OSError("Address in use"), None]

        start_port = 8080
        port = _find_available_port(start_port)

        assert port == start_port + 1
        assert mock_socket.bind.call_count == 2
        mock_socket.bind.assert_any_call(("127.0.0.1", start_port))
        mock_socket.bind.assert_any_call(("127.0.0.1", start_port + 1))


def test_find_available_port_failure():
    """Test behavior when no ports are available in range."""
    with patch("wet_mcp.searxng_runner.socket.socket") as mock_socket_cls:
        mock_socket = mock_socket_cls.return_value
        mock_socket.__enter__.return_value = mock_socket

        # Simulate bind failure on all calls
        mock_socket.bind.side_effect = OSError("Address in use")

        start_port = 8080
        max_tries = 5
        port = _find_available_port(start_port, max_tries=max_tries)

        # Should return start_port if all attempts fail (current implementation behavior)
        assert port == start_port
        assert mock_socket.bind.call_count == max_tries
