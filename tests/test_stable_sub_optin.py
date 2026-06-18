"""Guard: this server opts into username-stable-sub."""

import inspect

from wet_mcp import server


def test_enables_stable_sub():
    assert "stable_sub_enabled=True" in inspect.getsource(server)
