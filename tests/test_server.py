"""Tests for src/wet_mcp/server.py."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from wet_mcp.server import extract, help, search


@pytest.mark.asyncio
async def test_search_success():
    """Test search action success path."""
    with (
        patch("wet_mcp.server.ensure_searxng", new_callable=AsyncMock) as mock_ensure,
        patch("wet_mcp.server.searxng_search", new_callable=AsyncMock) as mock_search,
    ):
        mock_ensure.return_value = "http://localhost:8080"
        mock_search.return_value = "Search Results"

        result = await search(action="search", query="test query")

        assert result == "Search Results"
        mock_ensure.assert_called_once()
        mock_search.assert_called_once_with(
            searxng_url="http://localhost:8080",
            query="test query",
            categories="general",
            max_results=10,
        )


@pytest.mark.asyncio
async def test_search_missing_query():
    """Test search action missing query."""
    result = await search(action="search", query=None)
    assert "Error: query is required" in result


@pytest.mark.asyncio
async def test_extract_success():
    """Test extract action success path."""
    with patch("wet_mcp.server._extract", new_callable=AsyncMock) as mock_extract:
        mock_extract.return_value = "Extracted Content"

        result = await extract(action="extract", urls=["https://example.com"])

        assert result == "Extracted Content"
        mock_extract.assert_called_once_with(
            urls=["https://example.com"],
            format="markdown",
            stealth=False,
        )


@pytest.mark.asyncio
async def test_extract_with_options():
    """Test extract action with custom options."""
    with patch("wet_mcp.server._extract", new_callable=AsyncMock) as mock_extract:
        mock_extract.return_value = "Extracted Content"

        result = await extract(
            action="extract",
            urls=["https://example.com"],
            format="json",
            stealth=False,
        )

        assert result == "Extracted Content"
        mock_extract.assert_called_once_with(
            urls=["https://example.com"],
            format="json",
            stealth=False,
        )


@pytest.mark.asyncio
async def test_extract_missing_urls():
    """Test extract action missing urls."""
    result = await extract(action="extract", urls=None)
    assert "Error: urls is required" in result


@pytest.mark.asyncio
async def test_crawl_success():
    """Test crawl action success path."""
    with patch("wet_mcp.server._crawl", new_callable=AsyncMock) as mock_crawl:
        mock_crawl.return_value = "Crawl Results"

        result = await extract(
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
async def test_crawl_defaults():
    """Test crawl action with defaults."""
    with patch("wet_mcp.server._crawl", new_callable=AsyncMock) as mock_crawl:
        mock_crawl.return_value = "Crawl Results"

        result = await extract(action="crawl", urls=["https://example.com"])

        assert result == "Crawl Results"
        mock_crawl.assert_called_once_with(
            urls=["https://example.com"],
            depth=2,
            max_pages=20,
            format="markdown",
            stealth=False,
        )


@pytest.mark.asyncio
async def test_crawl_missing_urls():
    """Test crawl action missing urls."""
    result = await extract(action="crawl", urls=None)
    assert "Error: urls is required" in result


@pytest.mark.asyncio
async def test_map_success():
    """Test map action success path."""
    with patch("wet_mcp.server._sitemap", new_callable=AsyncMock) as mock_sitemap:
        mock_sitemap.return_value = "Sitemap Content"

        result = await extract(
            action="map", urls=["https://example.com"], depth=3, max_pages=50
        )

        assert result == "Sitemap Content"
        mock_sitemap.assert_called_once_with(
            urls=["https://example.com"],
            depth=3,
            max_pages=50,
        )


@pytest.mark.asyncio
async def test_map_defaults():
    """Test map action with defaults."""
    with patch("wet_mcp.server._sitemap", new_callable=AsyncMock) as mock_sitemap:
        mock_sitemap.return_value = "Sitemap Content"

        result = await extract(action="map", urls=["https://example.com"])

        assert result == "Sitemap Content"
        mock_sitemap.assert_called_once_with(
            urls=["https://example.com"],
            depth=2,
            max_pages=20,
        )


@pytest.mark.asyncio
async def test_map_missing_urls():
    """Test map action missing urls."""
    result = await extract(action="map", urls=None)
    assert "Error: urls is required" in result


@pytest.mark.asyncio
async def test_search_invalid_action():
    """Test invalid action on search tool."""
    result = await search(action="invalid_action")
    assert "Error: Unknown action" in result


@pytest.mark.asyncio
async def test_extract_invalid_action():
    """Test invalid action on extract tool."""
    result = await extract(action="invalid_action")
    assert "Error: Unknown action" in result


@pytest.mark.asyncio
async def test_help_success():
    """Test help tool success path."""
    mock_file = MagicMock()
    mock_file.read_text.return_value = "Mock Documentation"

    mock_files = MagicMock()
    mock_files.joinpath.return_value = mock_file

    with patch("wet_mcp.server.files", return_value=mock_files) as mock_files_fn:
        result = await help("test_tool")
        assert result == "Mock Documentation"
        mock_files_fn.assert_called_with("wet_mcp.docs")
        mock_files.joinpath.assert_called_with("test_tool.md")


@pytest.mark.asyncio
async def test_help_default():
    """Test help tool default argument."""
    mock_file = MagicMock()
    mock_file.read_text.return_value = "Search Documentation"

    mock_files = MagicMock()
    mock_files.joinpath.return_value = mock_file

    with patch("wet_mcp.server.files", return_value=mock_files) as mock_files_fn:
        result = await help()
        assert result == "Search Documentation"
        mock_files_fn.assert_called_with("wet_mcp.docs")
        mock_files.joinpath.assert_called_with("search.md")


@pytest.mark.asyncio
async def test_help_not_found():
    """Test help tool with missing documentation."""
    mock_files = MagicMock()
    mock_files.joinpath.side_effect = FileNotFoundError

    with patch("wet_mcp.server.files", return_value=mock_files):
        result = await help("non_existent")
        assert "Error: No documentation found" in result


@pytest.mark.asyncio
async def test_help_error():
    """Test help tool error handling."""
    mock_files = MagicMock()
    mock_files.joinpath.side_effect = Exception("Read error")

    with patch("wet_mcp.server.files", return_value=mock_files):
        result = await help("error_tool")
        assert "Error loading documentation: Read error" in result
