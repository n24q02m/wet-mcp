"""
Wrapper script to run SearXNG with runtime patches for Windows compatibility.

This replaces the fragile file-patching mechanism in setup.py.
"""
import os
import runpy
import sys
import types
from loguru import logger


def patch_windows_compatibility():
    """Apply runtime patches for Windows compatibility."""
    if sys.platform != "win32":
        return

    # Patch 1: Missing 'pwd' module
    # SearXNG imports 'pwd' at module level in valkeydb.py
    if "pwd" not in sys.modules:
        logger.debug("Patching missing 'pwd' module for Windows")
        pwd = types.ModuleType("pwd")

        def getpwuid(uid):
            # Return a dummy object with attributes expected by valkeydb.py error handler
            # usage: _pw.pw_name, _pw.pw_uid
            class PasswordEntry:
                def __init__(self, name, uid):
                    self.pw_name = name
                    self.pw_uid = uid
            return PasswordEntry("searx", uid)

        pwd.getpwuid = getpwuid
        sys.modules["pwd"] = pwd

    # Patch 2: Missing 'os.getuid'
    # Used in valkeydb.py: os.getuid()
    if not hasattr(os, "getuid"):
        logger.debug("Patching missing 'os.getuid' for Windows")
        # Return a dummy UID
        os.getuid = lambda: 1000


def main():
    try:
        patch_windows_compatibility()
        # Run the actual SearXNG webapp
        # This is equivalent to running `python -m searx.webapp`
        runpy.run_module("searx.webapp", run_name="__main__")
    except Exception as e:
        logger.exception(f"Failed to run SearXNG wrapper: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
