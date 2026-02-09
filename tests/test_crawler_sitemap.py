import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from wet_mcp.sources.crawler import sitemap


@pytest.fixture
def mock_crawler():
    """Mock the AsyncWebCrawler context manager and instance."""
    mock_instance = AsyncMock()
    mock_context = AsyncMock()
    mock_context.__aenter__.return_value = mock_instance
    mock_context.__aexit__.return_value = None
    return mock_context, mock_instance


@pytest.mark.asyncio
async def test_sitemap_basic(mock_crawler):
    """Test basic sitemap generation."""
    mock_context, mock_instance = mock_crawler

    # Mock crawl result
    mock_result = MagicMock()
    mock_result.success = True
    mock_result.links = {"internal": ["https://example.com/page1"]}
    mock_instance.arun.return_value = mock_result

    with patch("wet_mcp.sources.crawler.AsyncWebCrawler", return_value=mock_context):
        result = await sitemap(["https://example.com"], depth=1)

    data = json.loads(result)
    assert len(data) == 2
    assert data[0]["url"] == "https://example.com"
    assert data[1]["url"] == "https://example.com/page1"


@pytest.mark.asyncio
async def test_sitemap_dict_links(mock_crawler):
    """Test sitemap with dict links (bug fix verification)."""
    mock_context, mock_instance = mock_crawler

    # Mock crawl result with dict links
    mock_result = MagicMock()
    mock_result.success = True
    # Crawl4AI returns list of dicts for links
    mock_result.links = {
        "internal": [{"href": "https://example.com/page1", "text": "Page 1"}]
    }
    mock_instance.arun.return_value = mock_result

    with patch("wet_mcp.sources.crawler.AsyncWebCrawler", return_value=mock_context):
        result = await sitemap(["https://example.com"], depth=1)

    data = json.loads(result)
    assert len(data) == 2
    assert data[0]["url"] == "https://example.com"
    assert data[1]["url"] == "https://example.com/page1"


@pytest.mark.asyncio
async def test_sitemap_depth_limit(mock_crawler):
    """Test sitemap depth limit."""
    mock_context, mock_instance = mock_crawler

    # Configure mock to return new links based on input URL
    def side_effect(url, config=None):
        res = MagicMock()
        res.success = True
        if url == "https://example.com":
            res.links = {"internal": ["https://example.com/page1"]}
        elif url == "https://example.com/page1":
            res.links = {"internal": ["https://example.com/page2"]}
        else:
            res.links = {"internal": []}
        return res

    mock_instance.arun.side_effect = side_effect

    with patch("wet_mcp.sources.crawler.AsyncWebCrawler", return_value=mock_context):
        # Depth 1: should include root (0) and page1 (1), but NOT page2 (2)
        result = await sitemap(["https://example.com"], depth=1)

    data = json.loads(result)
    urls = [item["url"] for item in data]
    assert "https://example.com" in urls
    assert "https://example.com/page1" in urls
    assert "https://example.com/page2" not in urls
    assert len(data) == 2


@pytest.mark.asyncio
async def test_sitemap_max_pages(mock_crawler):
    """Test sitemap max pages limit."""
    mock_context, mock_instance = mock_crawler

    # Mock many links
    mock_result = MagicMock()
    mock_result.success = True
    # Generate 10 links
    mock_result.links = {
        "internal": [f"https://example.com/page{i}" for i in range(10)]
    }
    mock_instance.arun.return_value = mock_result

    with patch("wet_mcp.sources.crawler.AsyncWebCrawler", return_value=mock_context):
        result = await sitemap(["https://example.com"], depth=2, max_pages=5)

    data = json.loads(result)
    assert len(data) <= 5


@pytest.mark.asyncio
async def test_sitemap_error_handling(mock_crawler):
    """Test error handling during crawl."""
    mock_context, mock_instance = mock_crawler

    # Mock exception
    mock_instance.arun.side_effect = Exception("Network error")

    with patch("wet_mcp.sources.crawler.AsyncWebCrawler", return_value=mock_context):
        # Should not raise exception, but return partial result (just the root URL)
        result = await sitemap(["https://example.com"], depth=1)

    data = json.loads(result)
    assert len(data) == 1
    assert data[0]["url"] == "https://example.com"
