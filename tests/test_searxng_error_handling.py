import json
import unittest.mock

import httpx
import pytest

from wet_mcp.sources.searxng import _check_health, search


@pytest.mark.asyncio
async def test_check_health_httpx_exception():
    """Test that _check_health returns False when httpx raises an exception."""
    with unittest.mock.patch(
        "httpx.AsyncClient.get", side_effect=httpx.ConnectError("Connect failed")
    ):
        result = await _check_health("http://localhost:8080")
        assert result is False


@pytest.mark.asyncio
async def test_search_unhandled_exception_repro():
    """Reproduce missing error handling for non-SearchError exceptions."""
    # We want to see if a generic Exception is caught by search()
    # Currently it only catches SearchError.

    with unittest.mock.patch(
        "wet_mcp.sources.searxng._ensure_searxng_healthy",
        new_callable=unittest.mock.AsyncMock,
    ) as mock_healthy:
        mock_healthy.return_value = "http://localhost:8080"

        with unittest.mock.patch(
            "wet_mcp.sources.searxng._wc_search",
            side_effect=ValueError("Unexpected value error"),
        ):
            # If search() doesn't catch Exception, this will raise ValueError
            try:
                result = await search("http://localhost:8080", "test")
                json.loads(result)
                # If we get here and it didn't crash, it means it caught it (unexpectedly, based on current code)
                # or we are testing the wrong thing.
            except ValueError:
                pytest.fail(
                    "search() failed to catch generic Exception and return JSON error"
                )
            except Exception as e:
                pytest.fail(
                    f"search() raised unexpected exception: {type(e).__name__}: {e}"
                )


@pytest.mark.asyncio
async def test_search_httpx_exception_in_wc_search():
    """Test that httpx exceptions in _wc_search are handled if they bubble up."""
    # Depending on web-core implementation, it might bubble up httpx errors
    # if they are not caught there. But we saw web-core's search() catches them
    # and raises SearchError.
    # However, if some OTHER exception occurs, wet-mcp should still handle it.

    with unittest.mock.patch(
        "wet_mcp.sources.searxng._ensure_searxng_healthy",
        new_callable=unittest.mock.AsyncMock,
    ) as mock_healthy:
        mock_healthy.return_value = "http://localhost:8080"

        # Simulate an exception that web-core might NOT catch or a new one
        with unittest.mock.patch(
            "wet_mcp.sources.searxng._wc_search",
            side_effect=httpx.ReadTimeout("Timeout"),
        ):
            result = await search("http://localhost:8080", "test")
            data = json.loads(result)
            assert "error" in data
            assert "Timeout" in data["error"]


@pytest.mark.asyncio
async def test_check_health_bad_status():
    """Test that _check_health returns False when status is not 200."""
    mock_resp = unittest.mock.MagicMock()
    mock_resp.status_code = 500
    with unittest.mock.patch(
        "httpx.AsyncClient.get", new_callable=unittest.mock.AsyncMock
    ) as mock_get:
        mock_get.return_value = mock_resp
        result = await _check_health("http://localhost:8080")
        assert result is False


@pytest.mark.asyncio
async def test_check_health_timeout():
    """Test that _check_health returns False on timeout."""
    with unittest.mock.patch(
        "httpx.AsyncClient.get", side_effect=httpx.TimeoutException("Timeout")
    ):
        result = await _check_health("http://localhost:8080")
        assert result is False
