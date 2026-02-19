"""Tests for _with_timeout helper in server.py."""

import asyncio
import sys
from unittest.mock import MagicMock

import pytest

# Mock dependencies before import
mock_loguru = MagicMock()
sys.modules["loguru"] = mock_loguru

mock_mcp = MagicMock()
sys.modules["mcp"] = mock_mcp
sys.modules["mcp.server"] = MagicMock()
sys.modules["mcp.server.fastmcp"] = MagicMock()
sys.modules["mcp.types"] = MagicMock()

sys.modules["crawl4ai"] = MagicMock()
sys.modules["httpx"] = MagicMock()
sys.modules["pydantic"] = MagicMock()
sys.modules["pydantic_settings"] = MagicMock()
sys.modules["litellm"] = MagicMock()
sys.modules["sqlite_vec"] = MagicMock()

# Mock importlib.metadata to avoid PackageNotFoundError
mock_metadata = MagicMock()
mock_metadata.version.return_value = "0.0.0"
sys.modules["importlib.metadata"] = mock_metadata

# Mock internal modules to avoid import errors
sys.modules["wet_mcp.cache"] = MagicMock()
sys.modules["wet_mcp.db"] = MagicMock()
sys.modules["wet_mcp.searxng_runner"] = MagicMock()
sys.modules["wet_mcp.sources"] = MagicMock()
sys.modules["wet_mcp.sources.crawler"] = MagicMock()
sys.modules["wet_mcp.sources.searxng"] = MagicMock()
sys.modules["wet_mcp.embedder"] = MagicMock()
sys.modules["wet_mcp.reranker"] = MagicMock()
sys.modules["wet_mcp.setup"] = MagicMock()
sys.modules["wet_mcp.sync"] = MagicMock()

# Mock config
mock_settings = MagicMock()
mock_settings.tool_timeout = 120
mock_config = MagicMock()
mock_config.settings = mock_settings
sys.modules["wet_mcp.config"] = mock_config

# Now import the target function
from wet_mcp.server import _with_timeout  # noqa: E402, I001

@pytest.mark.asyncio
async def test_with_timeout_success():
    """Test _with_timeout returns result when task completes within timeout."""
    mock_settings.tool_timeout = 1.0

    async def fast_coro():
        return "success"

    result = await _with_timeout(fast_coro(), "test_action")
    assert result == "success"

@pytest.mark.asyncio
async def test_with_timeout_exceeded():
    """Test _with_timeout returns error message when task exceeds timeout."""
    mock_settings.tool_timeout = 0.1

    async def slow_coro():
        await asyncio.sleep(0.5)
        return "fail"

    result = await _with_timeout(slow_coro(), "test_action")
    expected_msg = (
        "Error: 'test_action' timed out after 0.1s. "
        "Increase TOOL_TIMEOUT or try simpler parameters."
    )
    assert result == expected_msg

@pytest.mark.asyncio
async def test_with_timeout_exception():
    """Test _with_timeout propagates exceptions from inner task."""
    mock_settings.tool_timeout = 1.0

    async def failing_coro():
        raise ValueError("oops")

    with pytest.raises(ValueError, match="oops"):
        await _with_timeout(failing_coro(), "test_action")

@pytest.mark.asyncio
async def test_with_timeout_disabled():
    """Test _with_timeout bypasses timeout logic when <= 0."""
    # Test with 0
    mock_settings.tool_timeout = 0
    async def coro1():
        return "success"
    result = await _with_timeout(coro1(), "test_action")
    assert result == "success"

    # Test with negative
    mock_settings.tool_timeout = -1
    async def coro2():
        return "success"
    result = await _with_timeout(coro2(), "test_action")
    assert result == "success"

@pytest.mark.asyncio
async def test_with_timeout_cleanup():
    """Test that cancelled task is given grace period for cleanup."""
    cleanup_done = [False]

    mock_settings.tool_timeout = 0.1

    async def cleanup_coro():
        try:
            await asyncio.sleep(0.5)
        finally:
            # This should run during the grace period
            cleanup_done[0] = True

    result = await _with_timeout(cleanup_coro(), "test_action")

    expected_msg = (
        "Error: 'test_action' timed out after 0.1s. "
        "Increase TOOL_TIMEOUT or try simpler parameters."
    )
    assert result == expected_msg
    # Verify cleanup ran
    assert cleanup_done[0] is True, "Cleanup block did not run"
