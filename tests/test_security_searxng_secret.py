from pathlib import Path
from unittest.mock import MagicMock, patch
import re

from wet_mcp.searxng_runner import _get_settings_path

def test_searxng_secret_key_replacement():
    """Verify that the placeholder secret key is replaced with a random hex string."""
    # Mock Path.home()
    mock_home = MagicMock(spec=Path)

    # Mock file operations
    mock_config_dir = MagicMock(spec=Path)
    mock_settings_file = MagicMock(spec=Path)

    # Chain the mocks
    mock_home.__truediv__.return_value = mock_config_dir
    mock_config_dir.__truediv__.return_value = mock_settings_file

    # Mock files("wet_mcp")
    mock_files = MagicMock()
    mock_bundled_file = MagicMock()
    mock_files.joinpath.return_value = mock_bundled_file

    # The content must contain the placeholder
    mock_bundled_file.read_text.return_value = (
        "server:\n"
        "  port: 41592\n"
        "  secret_key: \"REPLACE_WITH_REAL_SECRET\"\n"
    )

    with (
        patch("wet_mcp.searxng_runner.Path") as mock_path_cls,
        patch("wet_mcp.searxng_runner.os.getpid") as mock_getpid,
        patch("wet_mcp.searxng_runner.files", return_value=mock_files),
    ):
        mock_path_cls.home.return_value = mock_home
        mock_getpid.return_value = 12345

        port = 9090
        _get_settings_path(port)

        # Verify write_text called
        args, _ = mock_settings_file.write_text.call_args
        content = args[0]

        # Check port replacement
        assert "port: 9090" in content

        # Check secret key replacement
        assert "REPLACE_WITH_REAL_SECRET" not in content
        assert "secret_key: \"" in content

        # Extract the key to verify format
        match = re.search(r'secret_key: "([a-f0-9]+)"', content)
        assert match is not None, "Secret key not found or format incorrect"
        key = match.group(1)
        assert len(key) == 64  # 32 bytes hex = 64 chars
