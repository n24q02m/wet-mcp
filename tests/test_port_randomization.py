import unittest.mock

import pytest

from wet_mcp.searxng_runner import _find_available_port


def test_find_available_port_randomization():
    """Verify that _find_available_port tries ports in a randomized order."""
    start_port = 8080

    # Mock socket.bind to fail for some ports and succeed for others
    # We want to see which ports are tried.
    tried_ports = []

    class MockSocket:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def bind(self, address):
            port = address[1]
            tried_ports.append(port)
            # Fail all except one "random" one to see the sequence
            if port != 8500:  # Some high port
                raise OSError("Port in use")

        def close(self):
            pass

    with unittest.mock.patch("socket.socket", side_effect=MockSocket):
        try:
            _find_available_port(start_port, max_tries=500)
        except RuntimeError:
            pass  # We expect it might fail if we don't return from bind

    assert len(tried_ports) > 1
    # Check if they are tried in order. If they are randomized, they shouldn't be [8080, 8081, 8082, ...]
    is_ordered = all(
        tried_ports[i] <= tried_ports[i + 1] for i in range(len(tried_ports) - 1)
    )
    assert not is_ordered, (
        f"Ports were tried in deterministic order: {tried_ports[:10]}"
    )


def test_find_available_port_range():
    """Verify max_tries is respected."""
    start_port = 8080
    max_tries = 10

    tried_ports = []

    class MockSocket:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def bind(self, address):
            tried_ports.append(address[1])
            raise OSError("Port in use")

        def close(self):
            pass

    with unittest.mock.patch("socket.socket", side_effect=MockSocket):
        with pytest.raises(
            RuntimeError, match="No available port found in range 8080-8089"
        ):
            _find_available_port(start_port, max_tries=max_tries)

    assert len(tried_ports) == 10
    assert set(tried_ports) == set(range(8080, 8090))
