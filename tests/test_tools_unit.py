"""Unit tests for MCP tools in wet_mcp.server."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from wet_mcp.server import help as help_tool
from wet_mcp.server import media, web


# Mock settings to avoid timeouts affecting tests
@pytest.fixture(autouse=True)
def mock_settings():
    with patch("wet_mcp.server.settings") as mock:
        mock.tool_timeout = 0  # Disable timeout wrapper logic for easier testing
        mock.download_dir = "/tmp/downloads"
        mock.log_level = "INFO"
        yield mock


@pytest.mark.asyncio
async def test_web_search_success_returns_results():
    """Test web search action success."""
    with (
        patch("wet_mcp.server.ensure_searxng", new_callable=AsyncMock) as mock_ensure,
        patch("wet_mcp.server.searxng_search", new_callable=AsyncMock) as mock_search,
    ):
        mock_ensure.return_value = "http://localhost:8080"
        mock_search.return_value = "Found 10 results..."

        result = await web(action="search", query="test")

        assert result == "Found 10 results..."
        mock_ensure.assert_called_once()
        mock_search.assert_called_once_with(
            searxng_url="http://localhost:8080",
            query="test",
            categories="general",
            max_results=10,
        )


@pytest.mark.asyncio
async def test_web_search_missing_query_returns_error():
    """Test web search action fails without query."""
    result = await web(action="search")
    assert "Error: query is required" in result


@pytest.mark.asyncio
async def test_web_extract_success_returns_content():
    """Test web extract action success."""
    with patch("wet_mcp.server.extract", new_callable=AsyncMock) as mock_extract:
        mock_extract.return_value = "Extracted content..."

        result = await web(action="extract", urls=["http://example.com"])

        assert result == "Extracted content..."
        mock_extract.assert_called_once_with(
            urls=["http://example.com"], format="markdown", stealth=True
        )


@pytest.mark.asyncio
async def test_web_extract_missing_urls_returns_error():
    """Test web extract action fails without urls."""
    result = await web(action="extract")
    assert "Error: urls is required" in result


@pytest.mark.asyncio
async def test_web_crawl_success_returns_content():
    """Test web crawl action success."""
    with patch("wet_mcp.server.crawl", new_callable=AsyncMock) as mock_crawl:
        mock_crawl.return_value = "Crawled content..."

        result = await web(action="crawl", urls=["http://example.com"], depth=1)

        assert result == "Crawled content..."
        mock_crawl.assert_called_once()


@pytest.mark.asyncio
async def test_web_map_success_returns_sitemap():
    """Test web map action success."""
    with patch("wet_mcp.server.sitemap", new_callable=AsyncMock) as mock_sitemap:
        mock_sitemap.return_value = "Sitemap content..."

        result = await web(action="map", urls=["http://example.com"])

        assert result == "Sitemap content..."
        mock_sitemap.assert_called_once()


@pytest.mark.asyncio
async def test_web_unknown_action_returns_error():
    """Test web tool with unknown action returns error."""
    result = await web(action="unknown")
    assert "Error: Unknown action" in result


@pytest.mark.asyncio
async def test_media_list_success_returns_media():
    """Test media list action success."""
    with patch("wet_mcp.server.list_media", new_callable=AsyncMock) as mock_list:
        mock_list.return_value = "List of media..."

        result = await media(action="list", url="http://example.com")

        assert result == "List of media..."
        mock_list.assert_called_once()


@pytest.mark.asyncio
async def test_media_download_success_returns_status():
    """Test media download action success."""
    # Patch inside the function (local import)
    with patch(
        "wet_mcp.sources.crawler.download_media", new_callable=AsyncMock
    ) as mock_download:
        mock_download.return_value = "Downloaded 1 files..."

        result = await media(
            action="download", media_urls=["http://example.com/img.jpg"]
        )

        assert result == "Downloaded 1 files..."
        mock_download.assert_called_once()


@pytest.mark.asyncio
async def test_media_analyze_success_returns_analysis():
    """Test media analyze action success."""
    # Patch inside the function (local import)
    with patch("wet_mcp.llm.analyze_media", new_callable=AsyncMock) as mock_analyze:
        mock_analyze.return_value = "Image description..."

        result = await media(action="analyze", url="/tmp/img.jpg")

        assert result == "Image description..."
        mock_analyze.assert_called_once()


@pytest.mark.asyncio
async def test_help_success_returns_doc():
    """Test help tool returns documentation."""
    # Patch files to avoid FileNotFoundError
    with patch("wet_mcp.server.files") as mock_files:
        mock_path = MagicMock()
        mock_path.read_text.return_value = "Help content"
        mock_files.return_value.joinpath.return_value = mock_path

        result = await help_tool(tool_name="web")

        assert result == "Help content"


@pytest.mark.asyncio
async def test_help_missing_doc_returns_error():
    """Test help tool handles missing documentation."""
    with patch("wet_mcp.server.files") as mock_files:
        mock_files.return_value.joinpath.side_effect = FileNotFoundError

        result = await help_tool(tool_name="unknown")

        assert "Error: No documentation found" in result
