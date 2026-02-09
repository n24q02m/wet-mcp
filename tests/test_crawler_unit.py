import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from wet_mcp.sources.crawler import crawl


@pytest.fixture
def mock_crawler():
    """Fixture to mock AsyncWebCrawler."""
    mock_instance = AsyncMock()
    # Mock context manager
    mock_instance.__aenter__.return_value = mock_instance
    mock_instance.__aexit__.return_value = None
    return mock_instance


@pytest.mark.asyncio
async def test_crawl_basic_success(mock_crawler):
    """Test basic crawling functionality."""
    # Mock arun result
    mock_result = MagicMock()
    mock_result.success = True
    mock_result.markdown = "Mock Content"
    mock_result.cleaned_html = "<p>Mock Content</p>"
    mock_result.metadata = {"title": "Mock Title"}
    mock_result.links = {"internal": [], "external": []}

    mock_crawler.arun.return_value = mock_result

    with patch("wet_mcp.sources.crawler.AsyncWebCrawler", return_value=mock_crawler):
        result_json = await crawl(urls=["https://example.com"], depth=1, max_pages=10)

    results = json.loads(result_json)
    assert len(results) == 1
    assert results[0]["url"] == "https://example.com"
    assert results[0]["content"] == "Mock Content"
    assert results[0]["title"] == "Mock Title"
    assert results[0]["depth"] == 0


@pytest.mark.asyncio
async def test_crawl_depth_limit(mock_crawler):
    """Test that crawling respects the depth limit."""

    def side_effect(url, config=None):
        result = MagicMock()
        result.success = True
        result.markdown = f"Content for {url}"
        result.cleaned_html = f"<p>Content for {url}</p>"
        result.metadata = {"title": f"Title for {url}"}

        if url == "https://example.com":
            # Depth 0 -> 1
            result.links = {
                "internal": [{"href": "https://example.com/page2"}],
                "external": [],
            }
        elif url == "https://example.com/page2":
            # Depth 1 -> 2
            result.links = {
                "internal": [{"href": "https://example.com/page3"}],
                "external": [],
            }
        else:
            result.links = {"internal": [], "external": []}

        return result

    mock_crawler.arun.side_effect = side_effect

    with patch("wet_mcp.sources.crawler.AsyncWebCrawler", return_value=mock_crawler):
        # Set depth=1, so we should get Page 1 (depth 0) and Page 2 (depth 1), but NOT Page 3 (depth 2)
        result_json = await crawl(urls=["https://example.com"], depth=1, max_pages=10)

    results = json.loads(result_json)

    urls_crawled = [r["url"] for r in results]
    assert "https://example.com" in urls_crawled
    assert "https://example.com/page2" in urls_crawled
    assert "https://example.com/page3" not in urls_crawled
    assert len(results) == 2


@pytest.mark.asyncio
async def test_crawl_max_pages(mock_crawler):
    """Test that crawling respects the max_pages limit."""

    # Setup many pages
    def side_effect(url, config=None):
        result = MagicMock()
        result.success = True
        result.markdown = f"Content for {url}"
        result.cleaned_html = f"<p>Content for {url}</p>"
        result.metadata = {"title": f"Title for {url}"}

        # Determine next page
        if "page" in url:
            next_num = int(url.split("page")[-1]) + 1
        else:
            next_num = 2

        next_url = f"https://example.com/page{next_num}"
        result.links = {"internal": [{"href": next_url}], "external": []}
        return result

    mock_crawler.arun.side_effect = side_effect

    with patch("wet_mcp.sources.crawler.AsyncWebCrawler", return_value=mock_crawler):
        # Max pages = 3
        # Depth is high enough to allow 3 pages
        result_json = await crawl(
            urls=["https://example.com/page1"], depth=10, max_pages=3
        )

    results = json.loads(result_json)
    assert len(results) == 3
    urls = [r["url"] for r in results]
    assert "https://example.com/page1" in urls
    assert "https://example.com/page2" in urls
    assert "https://example.com/page3" in urls
    assert "https://example.com/page4" not in urls


@pytest.mark.asyncio
async def test_crawl_unsafe_url(mock_crawler):
    """Test that unsafe URLs are skipped."""

    with (
        patch("wet_mcp.sources.crawler.AsyncWebCrawler", return_value=mock_crawler),
        patch(
            "wet_mcp.sources.crawler.is_safe_url", return_value=False
        ) as mock_is_safe,
    ):
        result_json = await crawl(urls=["https://unsafe.com"])

    results = json.loads(result_json)
    assert len(results) == 0
    mock_crawler.arun.assert_not_called()
    mock_is_safe.assert_called_with("https://unsafe.com")


@pytest.mark.asyncio
async def test_crawl_error_handling(mock_crawler):
    """Test that exceptions during crawling are handled gracefully."""
    mock_crawler.arun.side_effect = Exception("Crawl failed")

    with patch("wet_mcp.sources.crawler.AsyncWebCrawler", return_value=mock_crawler):
        result_json = await crawl(urls=["https://example.com"])

    results = json.loads(result_json)
    # The current implementation logs the error but does NOT append to all_results
    assert len(results) == 0


@pytest.mark.asyncio
async def test_crawl_already_visited(mock_crawler):
    """Test that visited URLs are not re-crawled."""

    # Page A links to Page B
    # Page B links to Page A
    def side_effect(url, config=None):
        result = MagicMock()
        result.success = True
        result.markdown = f"Content for {url}"
        result.cleaned_html = f"<p>Content for {url}</p>"
        result.metadata = {"title": f"Title for {url}"}

        if url == "https://example.com/a":
            result.links = {
                "internal": [{"href": "https://example.com/b"}],
                "external": [],
            }
        elif url == "https://example.com/b":
            result.links = {
                "internal": [{"href": "https://example.com/a"}],
                "external": [],
            }
        else:
            result.links = {"internal": [], "external": []}

        return result

    mock_crawler.arun.side_effect = side_effect

    with patch("wet_mcp.sources.crawler.AsyncWebCrawler", return_value=mock_crawler):
        result_json = await crawl(urls=["https://example.com/a"], depth=5, max_pages=10)

    results = json.loads(result_json)
    assert len(results) == 2
    urls = [r["url"] for r in results]
    assert "https://example.com/a" in urls
    assert "https://example.com/b" in urls
    # Should not infinite loop
