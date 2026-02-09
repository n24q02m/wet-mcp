import builtins
import sys
from unittest.mock import MagicMock, patch

from wet_mcp import setup


def test_install_searxng_already_installed():
    """Test install_searxng returns True if searx is importable."""
    with patch.dict(sys.modules, {"searx": MagicMock()}):
        assert setup.install_searxng() is True


def test_install_searxng_install_path():
    """Test the installation path when searx is missing."""

    orig_import = builtins.__import__

    def mock_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "searx":
            raise ImportError("Mocked ImportError")
        return orig_import(name, globals, locals, fromlist, level)

    with (
        patch("builtins.__import__", side_effect=mock_import),
        patch("wet_mcp.setup.subprocess.run") as mock_run,
        patch("wet_mcp.setup.patch_searxng_version"),
        patch("wet_mcp.setup.patch_searxng_windows"),
    ):
        # Mock successful subprocess runs (deps and install)
        mock_run.return_value.returncode = 0

        assert setup.install_searxng() is True

        # Verify subprocess.run was called
        # Depending on implementation, it might be called 1 or 2 times (deps + install)
        assert mock_run.call_count == 2

        # Verify call args for second call (install)
        args, _ = mock_run.call_args_list[1]
        # args[0] is the command list
        cmd = args[0]
        assert "pip" in cmd
        assert "install" in cmd
        assert any("github.com/searxng/searxng" in arg for arg in cmd)


def test_install_searxng_failure():
    """Test installation failure."""
    orig_import = builtins.__import__

    def mock_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "searx":
            raise ImportError("Mocked ImportError")
        return orig_import(name, globals, locals, fromlist, level)

    with (
        patch("builtins.__import__", side_effect=mock_import),
        patch("wet_mcp.setup.subprocess.run") as mock_run,
    ):
        # Mock failure in deps
        mock_run.return_value.returncode = 1

        assert setup.install_searxng() is False
