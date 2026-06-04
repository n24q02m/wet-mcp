import json
import unittest.mock

import httpx
import pytest

from wet_mcp.sources.searxng import _check_health, _ensure_searxng_healthy, search


@pytest.mark.asyncio
async def test_check_health_success():
    with unittest.mock.patch(
        "httpx.AsyncClient.get", new_callable=unittest.mock.AsyncMock
    ) as mock_get:
        mock_get.return_value = unittest.mock.MagicMock(status_code=200)
        assert await _check_health("http://localhost:8080") is True


@pytest.mark.asyncio
async def test_check_health_failure_status():
    with unittest.mock.patch(
        "httpx.AsyncClient.get", new_callable=unittest.mock.AsyncMock
    ) as mock_get:
        mock_get.return_value = unittest.mock.MagicMock(status_code=500)
        assert await _check_health("http://localhost:8080") is False


@pytest.mark.asyncio
async def test_check_health_failure_exception():
    with unittest.mock.patch(
        "httpx.AsyncClient.get", side_effect=httpx.ConnectError("Refused")
    ):
        assert await _check_health("http://localhost:8080") is False


@pytest.mark.asyncio
async def test_ensure_searxng_healthy_already_healthy():
    with unittest.mock.patch(
        "wet_mcp.sources.searxng._check_health", new_callable=unittest.mock.AsyncMock
    ) as mock_check:
        mock_check.return_value = True
        url = await _ensure_searxng_healthy("http://localhost:8080")
        assert url == "http://localhost:8080"
        mock_check.assert_called_once_with("http://localhost:8080")


@pytest.mark.asyncio
async def test_ensure_searxng_healthy_restart_needed_and_succeeds():
    with unittest.mock.patch(
        "wet_mcp.sources.searxng._check_health", new_callable=unittest.mock.AsyncMock
    ) as mock_check:
        with unittest.mock.patch(
            "wet_mcp.searxng_runner.ensure_searxng",
            new_callable=unittest.mock.AsyncMock,
        ) as mock_ensure:
            mock_check.side_effect = [False, True]
            mock_ensure.return_value = "http://new-url:8080"

            url = await _ensure_searxng_healthy("http://old-url:8080")
            assert url == "http://new-url:8080"
            assert mock_check.call_count == 2
            mock_ensure.assert_called_once()


@pytest.mark.asyncio
async def test_ensure_searxng_healthy_restart_needed_but_still_unhealthy():
    with unittest.mock.patch(
        "wet_mcp.sources.searxng._check_health", new_callable=unittest.mock.AsyncMock
    ) as mock_check:
        with unittest.mock.patch(
            "wet_mcp.searxng_runner.ensure_searxng",
            new_callable=unittest.mock.AsyncMock,
        ) as mock_ensure:
            mock_check.side_effect = [False, False]
            mock_ensure.return_value = "http://new-url:8080"

            url = await _ensure_searxng_healthy("http://old-url:8080")
            assert url == "http://new-url:8080"
            assert mock_check.call_count == 2


@pytest.mark.asyncio
async def test_search_generic_exception_caught():
    # This test is expected to FAIL until we add the generic exception handling
    with unittest.mock.patch(
        "wet_mcp.sources.searxng._ensure_searxng_healthy",
        new_callable=unittest.mock.AsyncMock,
    ) as mock_healthy:
        mock_healthy.return_value = "http://localhost:8080"
        with unittest.mock.patch(
            "wet_mcp.sources.searxng._wc_search",
            side_effect=RuntimeError("Unexpected error"),
        ):
            result = await search("http://localhost:8080", "query")
            data = json.loads(result)
            assert "error" in data
            assert "Unexpected error" in data["error"]
