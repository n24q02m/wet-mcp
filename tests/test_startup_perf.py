import asyncio
import time
import pytest
from unittest.mock import patch, AsyncMock

# Mock run_auto_setup to be slow and blocking
def slow_setup():
    time.sleep(1.0) # Blocks the thread for 1 second

@pytest.mark.asyncio
async def test_startup_blocking_check():
    """
    Verify that server startup doesn't block the event loop.
    We'll run a concurrent background task (ticker) that updates a counter.
    If startup blocks the event loop, the ticker task won't run.
    """
    from wet_mcp.server import _lifespan

    # Background task to measure loop responsiveness
    # Should tick roughly every 0.1s
    metrics = {"ticks": 0}

    async def ticker():
        while True:
            metrics["ticks"] += 1
            await asyncio.sleep(0.1)

    ticker_task = asyncio.create_task(ticker())

    # We patch run_auto_setup to simulate a slow synchronous operation (1s)
    # We also mock ensure_searxng and stop_searxng to isolate the test
    with patch("wet_mcp.setup.run_auto_setup", side_effect=slow_setup) as mock_setup,          patch("wet_mcp.server.ensure_searxng", new_callable=AsyncMock) as mock_es,          patch("wet_mcp.server.stop_searxng"):

        mock_es.return_value = "http://mock-searxng"

        # Mock the server object passed to lifespan
        mock_server = object()

        start_time = time.time()

        # Run lifespan
        # If run_auto_setup is wrapped in to_thread, the loop yields control
        # during the 1s sleep, allowing ticker to increment ~10 times.
        # If run_auto_setup is blocking, the loop freezes, ticker doesn't run.
        async with _lifespan(mock_server):
            pass

        duration = time.time() - start_time

        # Verify that our slow_setup mock was actually called
        mock_setup.assert_called_once()

    # Cleanup ticker
    ticker_task.cancel()
    try:
        await ticker_task
    except asyncio.CancelledError:
        pass

    print(f"Startup duration: {duration:.2f}s")
    print(f"Ticks during startup: {metrics['ticks']}")

    # Assertions
    # With to_thread: sleep(1.0) allows ~10 ticks (0.1s each)
    # Without to_thread: sleep(1.0) blocks loop, 0 ticks (maybe 1 at start/end)
    assert metrics["ticks"] >= 5, f"Event loop was blocked! Ticks: {metrics['ticks']}"
