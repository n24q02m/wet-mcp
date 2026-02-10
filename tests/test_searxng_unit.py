"""Unit tests for SearXNG integration."""

import json
import unittest.mock

import httpx
import pytest

from wet_mcp.sources.searxng import search


@pytest.fixture
def mock_httpx_client():
    """Fixture to mock httpx.AsyncClient."""
    with unittest.mock.patch("httpx.AsyncClient") as mock_client:
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
async def test_search_http_error(mock_httpx_client):
    """Test search with HTTP error."""
    mock_response = unittest.mock.Mock()
    mock_response.status_code = 500
    error = httpx.HTTPStatusError(
        "Server Error", request=unittest.mock.Mock(), response=mock_response
    )

    mock_context = unittest.mock.AsyncMock()
    mock_context.get.return_value = mock_response
    mock_response.raise_for_status.side_effect = error
    mock_context.__aenter__.return_value = mock_context
    mock_httpx_client.return_value = mock_context

    result = await search(
        searxng_url="http://localhost:8080",
        query="error",
    )

    data = json.loads(result)
    assert "error" in data
    assert "HTTP error: 500" in data["error"]


@pytest.mark.asyncio
async def test_search_request_error(mock_httpx_client):
    """Test search with request error."""
    error = httpx.RequestError("Connection refused", request=unittest.mock.Mock())

    mock_context = unittest.mock.AsyncMock()
    mock_context.get.side_effect = error
    mock_context.__aenter__.return_value = mock_context
    mock_httpx_client.return_value = mock_context

    result = await search(
        searxng_url="http://localhost:8080",
        query="error",
    )

    data = json.loads(result)
    assert "error" in data
    assert "Request error" in data["error"]


@pytest.mark.asyncio
async def test_search_general_exception(mock_httpx_client):
    """Test search with general exception."""
    error = Exception("Unexpected error")

    mock_context = unittest.mock.AsyncMock()
    mock_context.get.side_effect = error
    mock_context.__aenter__.return_value = mock_context
    mock_httpx_client.return_value = mock_context

    result = await search(
        searxng_url="http://localhost:8080",
        query="error",
    )

    data = json.loads(result)
    assert "error" in data
    assert "Unexpected error" in data["error"]
