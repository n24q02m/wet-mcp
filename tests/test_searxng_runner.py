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
    """Test finding the first available port."""
    with patch("wet_mcp.searxng_runner.socket.socket") as mock_socket_cls:
        # Create a mock socket instance
        mock_socket = MagicMock()
        mock_socket_cls.return_value.__enter__.return_value = mock_socket

        # Call the function
        start_port = 8080
        port = _find_available_port(start_port)

        # Verify result
        assert port == start_port

        # Verify socket created and bind called
        mock_socket.bind.assert_called_once_with(("127.0.0.1", start_port))


def test_find_available_port_conflict():
    """Test finding a port when the first one is taken."""
    with patch("wet_mcp.searxng_runner.socket.socket") as mock_socket_cls:
        # Create a mock socket instance
        mock_socket = MagicMock()
        mock_socket_cls.return_value.__enter__.return_value = mock_socket

        # Configure side effect for bind:
        # First call raises OSError (port taken), second succeeds
        mock_socket.bind.side_effect = [OSError("Port in use"), None]

        # Call the function
        start_port = 8080
        port = _find_available_port(start_port)

        # Verify result is the next port
        assert port == start_port + 1

        # Verify socket created and bind called twice
        assert mock_socket.bind.call_count == 2
        mock_socket.bind.assert_any_call(("127.0.0.1", start_port))
        mock_socket.bind.assert_any_call(("127.0.0.1", start_port + 1))


def test_find_available_port_exhausted():
    """Test behavior when all ports in range are taken."""
    with patch("wet_mcp.searxng_runner.socket.socket") as mock_socket_cls:
        # Create a mock socket instance
        mock_socket = MagicMock()
        mock_socket_cls.return_value.__enter__.return_value = mock_socket

        # Always raise OSError
        mock_socket.bind.side_effect = OSError("Port in use")

        # Call the function with limited tries
        start_port = 8080
        max_tries = 3
        port = _find_available_port(start_port, max_tries=max_tries)

        # Verify result falls back to start_port
        assert port == start_port

        # Verify attempted max_tries times
        assert mock_socket.bind.call_count == max_tries
