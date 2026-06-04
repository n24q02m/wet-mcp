import asyncio
from unittest.mock import patch

import pytest

# Import only what's needed to minimize dependencies during collection
from wet_mcp.server import _with_timeout


@pytest.mark.asyncio
async def test_with_timeout_success():
    """Test _with_timeout returns result when task completes within timeout."""

    async def fast_coro():
        return "success"

    with patch("wet_mcp.server.settings") as mock_settings:
        mock_settings.tool_timeout = 1.0
        result = await _with_timeout(fast_coro(), "test_action")
        assert result == "success"


@pytest.mark.asyncio
async def test_with_timeout_exceeded():
    """Test _with_timeout returns error message when task exceeds timeout."""

    async def slow_coro():
        await asyncio.sleep(0.5)
        return "fail"

    with patch("wet_mcp.server.settings") as mock_settings:
        mock_settings.tool_timeout = 0.1
        # Mock _CANCEL_GRACE_PERIOD to be very small for faster tests
        with patch("wet_mcp.server._CANCEL_GRACE_PERIOD", 0.01):
            result = await _with_timeout(slow_coro(), "test_action")
            expected_msg = (
                "Error: 'test_action' timed out after 0.1s. "
                "Increase TOOL_TIMEOUT or try simpler parameters."
            )
            assert result == expected_msg


@pytest.mark.asyncio
async def test_with_timeout_exception():
    """Test _with_timeout propagates exceptions from inner task."""

    async def failing_coro():
        raise ValueError("oops")

    with patch("wet_mcp.server.settings") as mock_settings:
        mock_settings.tool_timeout = 1.0
        with pytest.raises(ValueError, match="oops"):
            await _with_timeout(failing_coro(), "test_action")


@pytest.mark.asyncio
async def test_with_timeout_disabled():
    """Test _with_timeout bypasses timeout logic when <= 0."""

    async def fast_coro():
        return "success"

    with patch("wet_mcp.server.settings") as mock_settings:
        # Test with 0
        mock_settings.tool_timeout = 0
        result = await _with_timeout(fast_coro(), "test_action")
        assert result == "success"

        # Test with negative
        mock_settings.tool_timeout = -1
        result = await _with_timeout(fast_coro(), "test_action")
        assert result == "success"


@pytest.mark.asyncio
async def test_with_timeout_cleanup():
    """Test that cancelled task is given grace period for cleanup."""
    cleanup_done = [False]

    async def cleanup_coro():
        try:
            await asyncio.sleep(0.5)
        finally:
            # This should run during the grace period
            cleanup_done[0] = True

    with patch("wet_mcp.server.settings") as mock_settings:
        mock_settings.tool_timeout = 0.1
        # Ensure _CANCEL_GRACE_PERIOD is enough for cleanup
        with patch("wet_mcp.server._CANCEL_GRACE_PERIOD", 0.2):
            result = await _with_timeout(cleanup_coro(), "test_action")

            assert "timed out after 0.1s" in result
            # Verify cleanup ran
            assert cleanup_done[0] is True, "Cleanup block did not run"


@pytest.mark.asyncio
async def test_with_timeout_grace_period_expired():
    """Test that _with_timeout returns even if cleanup takes too long."""
    cleanup_started = [False]

    async def very_slow_cleanup_coro():
        try:
            await asyncio.sleep(1.0)
        finally:
            cleanup_started[0] = True
            # This sleep is longer than the grace period
            await asyncio.sleep(0.5)

    with patch("wet_mcp.server.settings") as mock_settings:
        mock_settings.tool_timeout = 0.1
        # Small grace period
        with patch("wet_mcp.server._CANCEL_GRACE_PERIOD", 0.05):
            result = await _with_timeout(very_slow_cleanup_coro(), "test_action")

            assert "timed out after 0.1s" in result
            assert cleanup_started[0] is True
