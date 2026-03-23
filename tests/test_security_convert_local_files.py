from unittest.mock import patch

import pytest

from wet_mcp.sources.crawler import convert_local_files


@pytest.mark.asyncio
async def test_convert_local_files_default_home_directory(tmp_path):
    """Test that convert_local_files restricts to the home directory by default."""

    outside_file = tmp_path / "secret.txt"
    outside_file.write_text("sensitive info")

    home_dir = tmp_path / "home" / "user"
    home_dir.mkdir(parents=True)
    home_file = home_dir / "document.txt"
    home_file.write_text("hello world")

    mock_calls = []

    def mock_is_safe_local_path(path_str, allowed_dirs=None, max_size=None):
        mock_calls.append({"path": path_str, "allowed_dirs": allowed_dirs})
        return None

    # Patch the function where it is imported/defined
    with (
        patch("wet_mcp.config.settings.convert_allowed_dirs", ""),
        patch("pathlib.Path.home", return_value=home_dir),
        patch(
            "wet_mcp.security.is_safe_local_path", side_effect=mock_is_safe_local_path
        ),
    ):
        await convert_local_files([str(outside_file), str(home_file)])

        assert len(mock_calls) == 2
        for call in mock_calls:
            assert call["allowed_dirs"] is not None
            assert len(call["allowed_dirs"]) == 1
            assert call["allowed_dirs"][0] == home_dir.resolve()


@pytest.mark.asyncio
async def test_convert_local_files_custom_allowed_dirs(tmp_path):
    """Test that convert_local_files respects convert_allowed_dirs setting."""

    custom_dir_1 = tmp_path / "docs"
    custom_dir_2 = tmp_path / "work"
    custom_dir_1.mkdir()
    custom_dir_2.mkdir()

    mock_calls = []

    def mock_is_safe_local_path(path_str, allowed_dirs=None, max_size=None):
        mock_calls.append({"path": path_str, "allowed_dirs": allowed_dirs})
        return None

    with (
        patch(
            "wet_mcp.config.settings.convert_allowed_dirs",
            f"{custom_dir_1},{custom_dir_2}",
        ),
        patch(
            "wet_mcp.security.is_safe_local_path", side_effect=mock_is_safe_local_path
        ),
    ):
        await convert_local_files(["/tmp/file.txt"])

        assert len(mock_calls) == 1
        assert len(mock_calls[0]["allowed_dirs"]) == 2
        assert mock_calls[0]["allowed_dirs"][0] == custom_dir_1.resolve()
        assert mock_calls[0]["allowed_dirs"][1] == custom_dir_2.resolve()
