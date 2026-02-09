"""SearXNG wrapper to handle Windows compatibility.

This module is executed as a subprocess by searxng_runner.py.
It mocks necessary Unix-only modules (pwd, os.getuid) on Windows
before starting the SearXNG web application.
"""

import os
import runpy
import sys
import types


def _mock_windows_environment():
    """Mock Unix-specific modules/functions on Windows."""
    # Mock pwd module
    if "pwd" not in sys.modules:
        pwd = types.ModuleType("pwd")

        # Mock getpwuid result structure
        class PasswdStruct:
            def __init__(self, name, uid):
                self.pw_name = name
                self.pw_uid = uid

        # Mock getpwuid function
        # Returns dummy values that satisfy valkeydb.py logging
        pwd.getpwuid = lambda uid: PasswdStruct("winuser", uid)
        sys.modules["pwd"] = pwd

    # Mock os.getuid if missing
    if not hasattr(os, "getuid"):
        # We can attach it to the os module instance
        os.getuid = lambda: 1000  # Dummy UID


def main():
    if sys.platform == "win32":
        _mock_windows_environment()

    # Execute SearXNG webapp as __main__
    # This is equivalent to running `python -m searx.webapp`
    runpy.run_module("searx.webapp", run_name="__main__", alter_sys=True)


if __name__ == "__main__":
    main()
