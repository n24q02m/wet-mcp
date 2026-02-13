"""Tests for src/wet_mcp/server.py."""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from wet_mcp.config import settings
from wet_mcp.server import web


@pytest.mark.asyncio
async def test_web_search_success():
    """Test web search action success path."""
    with (
        patch("wet_mcp.server.ensure_searxng", new_callable=AsyncMock) as mock_ensure,
        patch("wet_mcp.server.searxng_search", new_callable=AsyncMock) as mock_search,
    ):
        mock_ensure.return_value = "http://localhost:8080"
        mock_search.return_value = "Search Results"

        result = await web(action="search", query="test query")

        assert result == "Search Results"
        mock_ensure.assert_called_once()
        mock_search.assert_called_once_with(
            searxng_url="http://localhost:8080",
            query="test query",
            categories="general",
            max_results=10,
        )


@pytest.mark.asyncio
async def test_web_search_missing_query():
    """Test web search action missing query."""
    result = await web(action="search", query=None)
    assert "Error: query is required" in result


@pytest.mark.asyncio
async def test_web_extract_success():
    """Test web extract action success path."""
    with patch("wet_mcp.server.extract", new_callable=AsyncMock) as mock_extract:
        mock_extract.return_value = "Extracted Content"

        result = await web(action="extract", urls=["https://example.com"])

        assert result == "Extracted Content"
        mock_extract.assert_called_once_with(
            urls=["https://example.com"],
            format="markdown",
            stealth=True,
        )


@pytest.mark.asyncio
async def test_web_extract_with_options():
    """Test web extract action with custom options."""
    with patch("wet_mcp.server.extract", new_callable=AsyncMock) as mock_extract:
        mock_extract.return_value = "Extracted Content"

        result = await web(
            action="extract", urls=["https://example.com"], format="json", stealth=False
        )

        assert result == "Extracted Content"
        mock_extract.assert_called_once_with(
            urls=["https://example.com"],
            format="json",
            stealth=False,
        )


@pytest.mark.asyncio
async def test_web_extract_missing_urls():
    """Test web extract action missing urls."""
    result = await web(action="extract", urls=None)
    assert "Error: urls is required" in result


@pytest.mark.asyncio
async def test_web_crawl_success():
    """Test web crawl action success path."""
    with patch("wet_mcp.server.crawl", new_callable=AsyncMock) as mock_crawl:
        mock_crawl.return_value = "Crawl Results"

        result = await web(
            action="crawl",
            urls=["https://example.com"],
            depth=3,
            max_pages=50,
            format="json",
            stealth=False,
        )

        assert result == "Crawl Results"
        mock_crawl.assert_called_once_with(
            urls=["https://example.com"],
            depth=3,
            max_pages=50,
            format="json",
            stealth=False,
        )


@pytest.mark.asyncio
async def test_web_crawl_defaults():
    """Test web crawl action with defaults."""
    with patch("wet_mcp.server.crawl", new_callable=AsyncMock) as mock_crawl:
        mock_crawl.return_value = "Crawl Results"

        result = await web(action="crawl", urls=["https://example.com"])

        assert result == "Crawl Results"
        mock_crawl.assert_called_once_with(
            urls=["https://example.com"],
            depth=2,
            max_pages=20,
            format="markdown",
            stealth=True,
        )


@pytest.mark.asyncio
async def test_web_crawl_missing_urls():
    """Test web crawl action missing urls."""
    result = await web(action="crawl", urls=None)
    assert "Error: urls is required" in result


@pytest.mark.asyncio
async def test_web_map_success():
    """Test web map action success path."""
    with patch("wet_mcp.server.sitemap", new_callable=AsyncMock) as mock_sitemap:
        mock_sitemap.return_value = "Sitemap Content"

        result = await web(
            action="map", urls=["https://example.com"], depth=3, max_pages=50
        )

        assert result == "Sitemap Content"
        mock_sitemap.assert_called_once_with(
            urls=["https://example.com"],
            depth=3,
            max_pages=50,
        )


@pytest.mark.asyncio
async def test_web_map_defaults():
    """Test web map action with defaults."""
    with patch("wet_mcp.server.sitemap", new_callable=AsyncMock) as mock_sitemap:
        mock_sitemap.return_value = "Sitemap Content"

        result = await web(action="map", urls=["https://example.com"])

        assert result == "Sitemap Content"
        mock_sitemap.assert_called_once_with(
            urls=["https://example.com"],
            depth=2,
            max_pages=20,
        )


@pytest.mark.asyncio
async def test_web_map_missing_urls():
    """Test web map action missing urls."""
    result = await web(action="map", urls=None)
    assert "Error: urls is required" in result


@pytest.mark.asyncio
async def test_web_invalid_action():
    """Test invalid action."""
    result = await web(action="invalid_action")
    assert "Error: Unknown action" in result


@pytest.mark.asyncio
async def test_web_timeout():
    """Test web action timeout."""
    async def slow_search(*args, **kwargs):
        await asyncio.sleep(0.2)
        return "Slow Result"

    with (
        patch("wet_mcp.server.ensure_searxng", new_callable=AsyncMock) as mock_ensure,
        patch("wet_mcp.server.searxng_search", new_callable=AsyncMock) as mock_search,
        patch.object(settings, "tool_timeout", 0.1),
    ):
        mock_ensure.return_value = "http://localhost:8080"
        mock_search.side_effect = slow_search

        result = await web(action="search", query="test query")

        assert "Error: 'search' timed out" in result
        mock_search.assert_called_once()


@pytest.mark.asyncio
async def test_web_exception_propagation():
    """Test web action exception propagation."""
    with (
        patch("wet_mcp.server.ensure_searxng", new_callable=AsyncMock) as mock_ensure,
        patch("wet_mcp.server.searxng_search", new_callable=AsyncMock) as mock_search,
    ):
        mock_ensure.return_value = "http://localhost:8080"
        mock_search.side_effect = ValueError("Test Error")

        with pytest.raises(ValueError, match="Test Error"):
            await web(action="search", query="test query")
