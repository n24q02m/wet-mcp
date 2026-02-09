"""Tests for searxng_wrapper module."""

import os
import sys
from unittest.mock import MagicMock, patch

from wet_mcp import searxng_wrapper


def test_main_windows(monkeypatch):
    """Test wrapper logic on Windows."""
    # Mock sys.platform
    monkeypatch.setattr(sys, "platform", "win32")

    # Mock runpy
    mock_runpy = MagicMock()
    monkeypatch.setattr("runpy.run_module", mock_runpy)

    # Ensure pwd is removed from modules so wrapper tries to mock it
    monkeypatch.delitem(sys.modules, "pwd", raising=False)

    # Ensure os.getuid is removed so wrapper tries to mock it
    monkeypatch.delattr(os, "getuid", raising=False)

    searxng_wrapper.main()

    # Verify pwd was mocked
    assert "pwd" in sys.modules
    pwd = sys.modules["pwd"]
    assert hasattr(pwd, "getpwuid")

    # Verify getpwuid return value
    pw_struct = pwd.getpwuid(123)
    assert pw_struct.pw_name == "winuser"
    assert pw_struct.pw_uid == 123

    # Verify os.getuid was mocked
    assert hasattr(os, "getuid")
    assert os.getuid() == 1000

    # Verify runpy was called
    mock_runpy.assert_called_once_with(
        "searx.webapp", run_name="__main__", alter_sys=True
    )


def test_main_linux(monkeypatch):
    """Test wrapper logic on Linux."""
    # Mock sys.platform
    monkeypatch.setattr(sys, "platform", "linux")

    # Mock runpy
    mock_runpy = MagicMock()
    monkeypatch.setattr("runpy.run_module", mock_runpy)

    # Spy on _mock_windows_environment
    with patch("wet_mcp.searxng_wrapper._mock_windows_environment") as mock_env:
        searxng_wrapper.main()
        mock_env.assert_not_called()

    # Verify runpy was called
    mock_runpy.assert_called_once_with(
        "searx.webapp", run_name="__main__", alter_sys=True
    )
