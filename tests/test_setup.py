"""Tests for setup module."""

from unittest.mock import MagicMock, patch

from wet_mcp.setup import _install_searxng


def test_install_searxng_already_installed():
    """Test _install_searxng returns True when searx is installed (using find_spec)."""
    with patch("importlib.util.find_spec") as mock_find_spec:
        mock_find_spec.return_value = MagicMock()

        # We ensure subprocess is NOT called
        with patch("subprocess.run") as mock_run:
            # We also need to patch sys.modules or ensure import searx doesn't fail
            # if we were running this on the old implementation AND searx was installed.
            # But since we assume it's NOT installed in the test env, import searx fails,
            # triggering the installation logic.
            # So on old code: import searx -> fails -> install -> fails the assertion.
            # On new code: find_spec -> success -> returns True -> passes assertion.

            assert _install_searxng() is True
            mock_run.assert_not_called()


def test_install_searxng_install_success():
    """Test _install_searxng installs searx when not present."""
    with (
        patch("importlib.util.find_spec") as mock_find_spec,
        patch("subprocess.run") as mock_run,
        patch("wet_mcp.setup.patch_searxng_version") as mock_patch_version,
        patch("wet_mcp.setup.patch_searxng_windows") as mock_patch_windows,
    ):
        # Simulate searx not installed
        mock_find_spec.return_value = None

        # Simulate successful installation
        mock_run.return_value.returncode = 0

        # We need to ensure import searx fails for the old implementation too.
        # Since it's not installed, it does fail.

        assert _install_searxng() is True

        # Should have tried to install dependencies and searxng
        assert mock_run.call_count == 2
        mock_patch_version.assert_called_once()
        mock_patch_windows.assert_called_once()


def test_install_searxng_deps_fail():
    """Test _install_searxng fails when dependencies fail to install."""
    with (
        patch("importlib.util.find_spec") as mock_find_spec,
        patch("subprocess.run") as mock_run,
    ):
        # Simulate searx not installed
        mock_find_spec.return_value = None

        # Simulate failed dependency installation
        mock_run.return_value.returncode = 1

        assert _install_searxng() is False
        assert mock_run.call_count == 1
