from pathlib import Path
from unittest.mock import MagicMock, patch

from wet_mcp.searxng_runner import _get_settings_path


def test_secret_key_replacement():
    """Verify that a random secret key is generated and injected."""
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

    # Mock the template content with the placeholder
    template_content = (
        "server:\n  port: 41592\n  secret_key: REPLACE_WITH_REAL_SECRET\n"
    )
    mock_bundled_file.read_text.return_value = template_content

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
        _get_settings_path(port)

        # Capture the content written to file
        args, _ = mock_settings_file.write_text.call_args
        written_content = args[0]

        # Verify port replacement
        assert "port: 9090" in written_content

        # Verify secret key replacement
        assert "REPLACE_WITH_REAL_SECRET" not in written_content
        assert "secret_key: " in written_content

        # Extract the secret key to verify length/format
        # "  secret_key: <secret>\n"
        for line in written_content.splitlines():
            if "secret_key:" in line:
                secret = line.split(":", 1)[1].strip()
                # 32 bytes hex = 64 chars
                assert len(secret) == 64
                # Verify it is hex
                int(secret, 16)
