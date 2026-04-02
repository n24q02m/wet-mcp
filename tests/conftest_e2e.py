"""Shared E2E test infrastructure for MCP servers.

Provides:
- --setup CLI option (relay | env | plugin)
- --browser CLI option (chrome | brave | edge)
- StderrCapture for relay URL detection
- open_browser() helper
- parse_result() / parse_result_allow_error() helpers

Copy this file to each MCP server's tests/ directory unchanged.
"""

from __future__ import annotations

import io
import os
import re
import subprocess
import sys
import threading
import time
from typing import TextIO

BROWSER_PATHS: dict[str, str] = {
    "chrome": r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    "brave": r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe",
    "edge": r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
}

RELAY_URL_PATTERN = re.compile(r"https?://\S+#k=[A-Za-z0-9+/=]+&p=\S+")


def pytest_addoption(parser):
    """Add --setup and --browser CLI options for E2E tests."""
    parser.addoption(
        "--setup",
        choices=["relay", "env", "plugin"],
        default="env",
        help="Server setup mode: relay (manual credentials), env (env vars), plugin (published package)",
    )
    parser.addoption(
        "--browser",
        default="chrome",
        choices=["chrome", "brave", "edge"],
        help="Browser to open relay page (only used with --setup=relay)",
    )


class StderrCapture:
    """Tee stderr to both a buffer and real stderr.

    Allows relay URL detection while still showing server logs to user.
    """

    def __init__(self, real_stderr: TextIO | None = None):
        self._buffer = io.StringIO()
        self._real_stderr = real_stderr or sys.stderr
        self._lock = threading.Lock()

    def write(self, text: str) -> int:
        with self._lock:
            self._buffer.write(text)
        return self._real_stderr.write(text)

    def flush(self) -> None:
        self._real_stderr.flush()

    @property
    def fileno(self):
        """Delegate fileno to real stderr for compatibility."""
        return self._real_stderr.fileno

    def get_relay_url(self, timeout: float = 30.0) -> str | None:
        """Wait for relay URL to appear in captured stderr."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with self._lock:
                match = RELAY_URL_PATTERN.search(self._buffer.getvalue())
            if match:
                return match.group(0)
            time.sleep(0.5)
        return None

    def get_output(self) -> str:
        with self._lock:
            return self._buffer.getvalue()


def open_browser(url: str, browser: str = "chrome") -> None:
    """Open URL in specified browser."""
    exe = BROWSER_PATHS.get(browser)
    if exe and os.path.exists(exe):
        subprocess.Popen(
            [exe, url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
    else:
        import webbrowser

        webbrowser.open(url)


def parse_result(r) -> str:
    """Extract text from MCP tool result. Raise on error."""
    if hasattr(r, "isError") and r.isError:
        raise AssertionError(f"Tool returned error: {r.content[0].text}")
    return r.content[0].text


def parse_result_allow_error(r) -> str:
    """Extract text from MCP tool result, including errors."""
    return r.content[0].text
