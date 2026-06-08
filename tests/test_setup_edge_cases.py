from unittest.mock import patch

from wet_mcp.setup import patch_searxng_version, patch_searxng_windows


@patch("wet_mcp.setup._find_searx_package_dir")
@patch("wet_mcp.setup.Path")
def test_patch_searxng_version_no_dir_noop(mock_path, mock_find_dir):
    """
    Test that patch_searxng_version returns immediately when no searx directory is found,
    without performing any Path operations.
    """
    mock_find_dir.return_value = None

    patch_searxng_version()

    # Assert that find_dir was called
    mock_find_dir.assert_called_once()

    # Assert that no Path object was created or manipulated
    # Note: Path() might be called for other things if we are not careful,
    # but here we specifically want to see that searx_dir was not used.
    # If it returned early, it shouldn't have reached 'vf = searx_dir / "version_frozen.py"'
    mock_path.assert_not_called()


@patch("platform.system", return_value="Windows")
@patch("wet_mcp.setup._find_searx_package_dir")
@patch("wet_mcp.setup.Path")
def test_patch_searxng_windows_no_dir_noop(mock_path, mock_find_dir, mock_system):
    """
    Test that patch_searxng_windows returns immediately when no searx directory is found,
    without performing any Path operations.
    """
    mock_find_dir.return_value = None

    patch_searxng_windows()

    # Assert that find_dir was called
    mock_find_dir.assert_called_once()

    # Assert that no Path object was created or manipulated
    mock_path.assert_not_called()
