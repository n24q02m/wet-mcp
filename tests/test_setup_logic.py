import sys
import importlib.util
from unittest.mock import MagicMock, patch
from wet_mcp.setup import _install_searxng

def test_install_searxng_checks_installed():
    """Test that _install_searxng checks for installation without importing."""
    # We patch importlib.util.find_spec to return a spec (simulating installed)
    with patch("importlib.util.find_spec") as mock_find_spec:
        mock_spec = MagicMock()
        mock_find_spec.return_value = mock_spec

        # Call the function
        result = _install_searxng()

        # Verify it returns True
        assert result is True

        # Verify it called find_spec with "searx"
        mock_find_spec.assert_called_with("searx")

def test_install_searxng_not_installed():
    """Test _install_searxng when searx is not installed."""
    with patch("importlib.util.find_spec") as mock_find_spec:
        mock_find_spec.return_value = None

        with patch("subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0

            with patch("wet_mcp.setup.patch_searxng_version"),                  patch("wet_mcp.setup.patch_searxng_windows"):

                assert _install_searxng() is True
                assert mock_run.called
