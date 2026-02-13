import sys
import types
from unittest.mock import MagicMock, patch
import pytest

# We need to import the module under test.
# Since it is a script, we can import it if it's in python path.
from wet_mcp.run_searxng import patch_windows_compatibility

def test_patch_windows_compatibility_linux():
    """Verify that no patches are applied on Linux."""
    with patch("sys.platform", "linux"):
        # Ensure clean slate
        with patch.dict(sys.modules, clear=False):
            if "pwd" in sys.modules:
                del sys.modules["pwd"]

            patch_windows_compatibility()

            # Verify pwd was NOT added
            assert "pwd" not in sys.modules

def test_patch_windows_compatibility_windows():
    """Verify that patches are applied on Windows."""
    with patch("sys.platform", "win32"):
        # Mock sys.modules to simulate missing pwd
        with patch.dict(sys.modules, clear=False):
            if "pwd" in sys.modules:
                del sys.modules["pwd"]

            # Mock os to simulate missing getuid
            with patch("wet_mcp.run_searxng.os", spec=object) as mock_os:
                # Ensure getuid is missing
                if hasattr(mock_os, "getuid"):
                     del mock_os.getuid

                # Execute the patch
                patch_windows_compatibility()

                # Verify pwd was added
                assert "pwd" in sys.modules
                pwd_module = sys.modules["pwd"]
                assert hasattr(pwd_module, "getpwuid")

                # Verify getpwuid behavior
                entry = pwd_module.getpwuid(123)
                assert entry.pw_name == "searx"
                assert entry.pw_uid == 123

                # Verify os.getuid was patched
                assert hasattr(mock_os, "getuid")
                assert mock_os.getuid() == 1000
