from pathlib import Path
from unittest.mock import MagicMock, patch

from wet_mcp.searxng_runner import _get_settings_path, _find_available_port


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


def test_find_available_port_success():
    start_port = 8080

    # Mock socket context manager
    mock_socket_instance = MagicMock()
    mock_socket_instance.__enter__.return_value = mock_socket_instance
    mock_socket_instance.__exit__.return_value = None

    with patch("wet_mcp.searxng_runner.socket.socket", return_value=mock_socket_instance) as mock_socket_ctor,          patch("random.shuffle", side_effect=lambda x: None):  # No-op shuffle

        port = _find_available_port(start_port)

        assert port == 8080
        mock_socket_ctor.assert_called()
        mock_socket_instance.bind.assert_called_with(("127.0.0.1", 8080))


def test_find_available_port_collision():
    start_port = 8080

    # Mock socket context manager
    mock_socket_instance = MagicMock()
    mock_socket_instance.__enter__.return_value = mock_socket_instance
    mock_socket_instance.__exit__.return_value = None

    # First bind fails, second succeeds
    mock_socket_instance.bind.side_effect = [OSError("Address in use"), None]

    with patch("wet_mcp.searxng_runner.socket.socket", return_value=mock_socket_instance) as mock_socket_ctor,          patch("random.shuffle", side_effect=lambda x: None):  # No-op shuffle

        port = _find_available_port(start_port)

        assert port == 8081
        assert mock_socket_ctor.call_count == 2
        # Verify calls
        mock_socket_instance.bind.assert_any_call(("127.0.0.1", 8080))
        mock_socket_instance.bind.assert_any_call(("127.0.0.1", 8081))


def test_find_available_port_all_taken():
    start_port = 8080
    max_tries = 3

    # Mock socket context manager
    mock_socket_instance = MagicMock()
    mock_socket_instance.__enter__.return_value = mock_socket_instance
    mock_socket_instance.__exit__.return_value = None

    # Always fail
    mock_socket_instance.bind.side_effect = OSError("Address in use")

    with patch("wet_mcp.searxng_runner.socket.socket", return_value=mock_socket_instance) as mock_socket_ctor,          patch("random.shuffle", side_effect=lambda x: None):  # No-op shuffle

        port = _find_available_port(start_port, max_tries=max_tries)

        # Returns start_port if all fail (based on implementation)
        assert port == 8080
        assert mock_socket_ctor.call_count == max_tries
