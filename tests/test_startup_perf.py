import asyncio
import time
from unittest.mock import MagicMock, patch

import pytest


async def monitor_loop(interval=0.1):
    """Monitor event loop blocking."""
    max_delay = 0
    start = time.time()
    while True:
        step_start = time.time()
        await asyncio.sleep(interval)
        step_end = time.time()
        delay = step_end - step_start - interval
        max_delay = max(max_delay, delay)
        # Stop if 2 seconds passed
        if time.time() - start > 2:
            break
    return max_delay


@pytest.mark.asyncio
async def test_server_startup_non_blocking():
    """Test that server startup setup does not block the event loop."""

    # Mock run_auto_setup to take time
    def slow_setup():
        time.sleep(1.0)  # Simulate 1s synchronous work
        return True

    # Patch modules
    # Patch wet_mcp.setup.run_auto_setup instead of wet_mcp.server.run_auto_setup
    with (
        patch("wet_mcp.setup.run_auto_setup", side_effect=slow_setup) as mock_setup,
        patch("wet_mcp.server.settings"),
        patch("wet_mcp.server.ensure_searxng", new_callable=MagicMock) as mock_ensure,
        patch("wet_mcp.server.stop_searxng"),
    ):
        # Mock ensure_searxng to be an async mock
        mock_ensure.return_value = "http://localhost:8080"

        async def async_ensure():
            return "http://localhost:8080"

        mock_ensure.side_effect = async_ensure

        from wet_mcp.server import _lifespan, mcp

        # Start the monitor task
        monitor_task = asyncio.create_task(monitor_loop())

        # Run lifespan
        async with _lifespan(mcp):
            pass

        max_delay = await monitor_task

        # If max_delay is close to 1.0, it means the loop was blocked
        print(f"Max loop delay: {max_delay:.4f}s")
        assert max_delay < 0.5, f"Event loop was blocked for {max_delay:.4f}s"
        assert mock_setup.called
