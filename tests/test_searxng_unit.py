"""Unit tests for SearXNG integration with retry logic."""

import json
import unittest.mock

import httpx
import pytest

from wet_mcp.sources.searxng import search


@pytest.fixture(autouse=True)
def mock_health_check():
    """Mock _ensure_searxng_healthy to prevent real SearXNG startup in unit tests."""
    with unittest.mock.patch(
        "wet_mcp.sources.searxng._ensure_searxng_healthy",
        new_callable=unittest.mock.AsyncMock,
    ) as mock_healthy:
        # By default, return the same URL that was passed in
        mock_healthy.side_effect = lambda url: url
        yield mock_healthy


@pytest.fixture
def mock_httpx_client():
    """Fixture to mock httpx.AsyncClient."""
    with unittest.mock.patch(
        "wet_mcp.sources.searxng.httpx.AsyncClient"
    ) as mock_client:
        yield mock_client


@pytest.mark.asyncio
async def test_search_success(mock_httpx_client):
    """Test successful search."""
    mock_response = unittest.mock.Mock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "results": [
            {
                "url": "https://example.com",
                "title": "Example Domain",
                "content": "This domain is for use in illustrative examples in documents.",
                "engine": "google",
            }
        ]
    }

    mock_context = unittest.mock.AsyncMock()
    mock_context.get.return_value = mock_response
    mock_context.__aenter__.return_value = mock_context
    mock_httpx_client.return_value = mock_context

    result = await search(
        searxng_url="http://localhost:8080",
        query="example",
        categories="general",
        max_results=1,
    )

    data = json.loads(result)
    assert data["query"] == "example"
    assert data["total"] == 1
    assert len(data["results"]) == 1
    assert data["results"][0]["url"] == "https://example.com"
    assert data["results"][0]["title"] == "Example Domain"


@pytest.mark.asyncio
async def test_search_empty(mock_httpx_client):
    """Test search with no results."""
    mock_response = unittest.mock.Mock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"results": []}

    mock_context = unittest.mock.AsyncMock()
    mock_context.get.return_value = mock_response
    mock_context.__aenter__.return_value = mock_context
    mock_httpx_client.return_value = mock_context

    result = await search(
        searxng_url="http://localhost:8080",
        query="nonexistent",
    )

    data = json.loads(result)
    assert data["query"] == "nonexistent"
    assert data["total"] == 0
    assert len(data["results"]) == 0


@pytest.mark.asyncio
async def test_search_http_error_5xx_retries(mock_httpx_client):
    """Test search retries on 5xx server errors."""
    mock_response_500 = unittest.mock.Mock()
    mock_response_500.status_code = 500

    error = httpx.HTTPStatusError(
        "Server Error", request=unittest.mock.Mock(), response=mock_response_500
    )
    mock_response_500.raise_for_status.side_effect = error

    # Success response for retry
    mock_response_ok = unittest.mock.Mock()
    mock_response_ok.status_code = 200
    mock_response_ok.json.return_value = {
        "results": [
            {
                "url": "https://example.com",
                "title": "Example",
                "content": "Content",
                "engine": "google",
            }
        ]
    }
    mock_response_ok.raise_for_status = unittest.mock.Mock()

    mock_context = unittest.mock.AsyncMock()
    # First call fails with 500, second succeeds
    mock_context.get.side_effect = [mock_response_500, mock_response_ok]
    mock_context.__aenter__.return_value = mock_context
    mock_httpx_client.return_value = mock_context

    with unittest.mock.patch(
        "wet_mcp.sources.searxng.asyncio.sleep", new_callable=unittest.mock.AsyncMock
    ):
        result = await search(
            searxng_url="http://localhost:8080",
            query="retry_test",
        )

    data = json.loads(result)
    assert data["query"] == "retry_test"
    assert data["total"] == 1


@pytest.mark.asyncio
async def test_search_http_error_4xx_no_retry(mock_httpx_client):
    """Test search does NOT retry on 4xx client errors."""
    mock_response = unittest.mock.Mock()
    mock_response.status_code = 400
    error = httpx.HTTPStatusError(
        "Bad Request", request=unittest.mock.Mock(), response=mock_response
    )
    mock_response.raise_for_status.side_effect = error

    mock_context = unittest.mock.AsyncMock()
    mock_context.get.return_value = mock_response
    mock_context.__aenter__.return_value = mock_context
    mock_httpx_client.return_value = mock_context

    result = await search(
        searxng_url="http://localhost:8080",
        query="error",
    )

    data = json.loads(result)
    assert "error" in data
    assert "HTTP error: 400" in data["error"]
    # Should only call get once (no retry for 4xx)
    assert mock_context.get.call_count == 1


@pytest.mark.asyncio
async def test_search_http_error_5xx_all_retries_exhausted(mock_httpx_client):
    """Test search returns error after all retries exhausted on 5xx."""
    mock_response = unittest.mock.Mock()
    mock_response.status_code = 500
    error = httpx.HTTPStatusError(
        "Server Error", request=unittest.mock.Mock(), response=mock_response
    )
    mock_response.raise_for_status.side_effect = error

    mock_context = unittest.mock.AsyncMock()
    mock_context.get.return_value = mock_response
    mock_context.__aenter__.return_value = mock_context
    mock_httpx_client.return_value = mock_context

    with unittest.mock.patch(
        "wet_mcp.sources.searxng.asyncio.sleep", new_callable=unittest.mock.AsyncMock
    ):
        result = await search(
            searxng_url="http://localhost:8080",
            query="error",
        )

    data = json.loads(result)
    assert "error" in data
    assert "HTTP error: 500" in data["error"]
    # Should have retried 3 times
    assert mock_context.get.call_count == 3


@pytest.mark.asyncio
async def test_search_request_error_retries(mock_httpx_client):
    """Test search retries on connection errors and triggers health check."""
    error = httpx.RequestError("Connection refused", request=unittest.mock.Mock())

    # Success response for retry
    mock_response_ok = unittest.mock.Mock()
    mock_response_ok.status_code = 200
    mock_response_ok.json.return_value = {
        "results": [
            {
                "url": "https://example.com",
                "title": "Example",
                "content": "Content",
                "engine": "google",
            }
        ]
    }
    mock_response_ok.raise_for_status = unittest.mock.Mock()

    mock_context = unittest.mock.AsyncMock()
    # First call fails, second succeeds
    mock_context.get.side_effect = [error, mock_response_ok]
    mock_context.__aenter__.return_value = mock_context
    mock_httpx_client.return_value = mock_context

    with unittest.mock.patch(
        "wet_mcp.sources.searxng.asyncio.sleep", new_callable=unittest.mock.AsyncMock
    ):
        result = await search(
            searxng_url="http://localhost:8080",
            query="retry_connect",
        )

    data = json.loads(result)
    assert data["query"] == "retry_connect"
    assert data["total"] == 1


@pytest.mark.asyncio
async def test_search_request_error_all_retries_exhausted(mock_httpx_client):
    """Test search returns error after all retries exhausted on request error."""
    error = httpx.RequestError("Connection refused", request=unittest.mock.Mock())

    mock_context = unittest.mock.AsyncMock()
    mock_context.get.side_effect = error
    mock_context.__aenter__.return_value = mock_context
    mock_httpx_client.return_value = mock_context

    with unittest.mock.patch(
        "wet_mcp.sources.searxng.asyncio.sleep", new_callable=unittest.mock.AsyncMock
    ):
        result = await search(
            searxng_url="http://localhost:8080",
            query="error",
        )

    data = json.loads(result)
    assert "error" in data
    assert "Request error" in data["error"]


@pytest.mark.asyncio
async def test_search_general_exception(mock_httpx_client):
    """Test search with general exception retries then fails."""
    error = Exception("Unexpected error")

    mock_context = unittest.mock.AsyncMock()
    mock_context.get.side_effect = error
    mock_context.__aenter__.return_value = mock_context
    mock_httpx_client.return_value = mock_context

    with unittest.mock.patch(
        "wet_mcp.sources.searxng.asyncio.sleep", new_callable=unittest.mock.AsyncMock
    ):
        result = await search(
            searxng_url="http://localhost:8080",
            query="error",
        )

    data = json.loads(result)
    assert "error" in data
    assert "Unexpected error" in data["error"]


@pytest.mark.asyncio
async def test_search_health_check_called(mock_health_check, mock_httpx_client):
    """Test that _ensure_searxng_healthy is called before search."""
    mock_response = unittest.mock.Mock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"results": []}

    mock_context = unittest.mock.AsyncMock()
    mock_context.get.return_value = mock_response
    mock_context.__aenter__.return_value = mock_context
    mock_httpx_client.return_value = mock_context

    await search(
        searxng_url="http://localhost:8080",
        query="health_check_test",
    )

    mock_health_check.assert_called_once_with("http://localhost:8080")


@pytest.mark.asyncio
async def test_search_uses_healthy_url(mock_health_check, mock_httpx_client):
    """Test that search uses the URL returned by health check (may differ from input)."""
    # Health check returns a different URL (e.g. after port change)
    mock_health_check.side_effect = None
    mock_health_check.return_value = "http://127.0.0.1:9090"

    mock_response = unittest.mock.Mock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"results": []}

    mock_context = unittest.mock.AsyncMock()
    mock_context.get.return_value = mock_response
    mock_context.__aenter__.return_value = mock_context
    mock_httpx_client.return_value = mock_context

    await search(
        searxng_url="http://localhost:8080",
        query="url_test",
    )

    # Verify the search request went to the healthy URL, not the original
    call_args = mock_context.get.call_args
    assert "http://127.0.0.1:9090/search" in str(call_args)


@pytest.mark.asyncio
async def test_search_max_results_respected(mock_httpx_client):
    """Test that max_results parameter is respected."""
    mock_response = unittest.mock.Mock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "results": [
            {
                "url": f"https://example.com/{i}",
                "title": f"Result {i}",
                "content": f"Content {i}",
                "engine": "google",
            }
            for i in range(20)
        ]
    }

    mock_context = unittest.mock.AsyncMock()
    mock_context.get.return_value = mock_response
    mock_context.__aenter__.return_value = mock_context
    mock_httpx_client.return_value = mock_context

    result = await search(
        searxng_url="http://localhost:8080",
        query="many_results",
        max_results=5,
    )

    data = json.loads(result)
    assert data["total"] == 5
    assert len(data["results"]) == 5


@pytest.mark.asyncio
async def test_search_result_format(mock_httpx_client):
    """Test that search results are formatted correctly."""
    mock_response = unittest.mock.Mock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "results": [
            {
                "url": "https://example.com",
                "title": "Example Title",
                "content": "Example snippet text",
                "engine": "duckduckgo",
                "extra_field": "should be ignored",
            }
        ]
    }

    mock_context = unittest.mock.AsyncMock()
    mock_context.get.return_value = mock_response
    mock_context.__aenter__.return_value = mock_context
    mock_httpx_client.return_value = mock_context

    result = await search(
        searxng_url="http://localhost:8080",
        query="format_test",
    )

    data = json.loads(result)
    r = data["results"][0]
    assert r["url"] == "https://example.com"
    assert r["title"] == "Example Title"
    assert r["snippet"] == "Example snippet text"
    assert r["source"] == "duckduckgo"
    assert "extra_field" not in r
