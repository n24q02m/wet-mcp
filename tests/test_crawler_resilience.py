import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from wet_mcp.sources.crawler import _get_crawler, crawl, list_media, sitemap


@pytest.mark.asyncio
async def test_crawl_resilience(mock_crawler_instance):
    """Test that crawl continues even if some URLs fail."""

    def side_effect(url, config=None):
        if "fail" in url:
            raise Exception("Crawl failed for " + url)

        mock_result = MagicMock()
        mock_result.success = True
        mock_result.markdown = f"Content for {url}"
        mock_result.metadata = {"title": f"Title for {url}"}
        mock_result.links = {"internal": [], "external": []}
        return mock_result

    mock_crawler_instance.arun = AsyncMock(side_effect=side_effect)

    with patch(
        "wet_mcp.sources.crawler._get_crawler",
        new_callable=AsyncMock,
        return_value=mock_crawler_instance,
    ):
        # We try to crawl two URLs, one that fails and one that succeeds
        result_json = await crawl(
            urls=["https://fail.com", "https://success.com"], depth=0
        )

    results = json.loads(result_json)
    assert len(results) == 1
    assert results[0]["url"] == "https://success.com"
    assert results[0]["content"] == "Content for https://success.com"


@pytest.mark.asyncio
async def test_sitemap_resilience(mock_crawler_instance):
    """Test that sitemap continues mapping even if some URLs fail."""

    def side_effect(url, config=None):
        if "fail" in url:
            raise Exception("Mapping failed for " + url)

        mock_result = MagicMock()
        mock_result.success = True
        mock_result.links = {"internal": [], "external": []}
        return mock_result

    mock_crawler_instance.arun = AsyncMock(side_effect=side_effect)

    with patch(
        "wet_mcp.sources.crawler._get_crawler",
        new_callable=AsyncMock,
        return_value=mock_crawler_instance,
    ):
        # One root fails, one root succeeds
        result_json = await sitemap(
            urls=["https://fail.com", "https://success.com"], depth=0
        )

    results = json.loads(result_json)
    assert len(results) == 2
    urls = [r["url"] for r in results]
    assert "https://fail.com" in urls
    assert "https://success.com" in urls


@pytest.mark.asyncio
async def test_get_crawler_retry():
    """Test that _get_crawler retries once on failure."""
    import wet_mcp.sources.crawler as crawler_mod

    # We need to mock AsyncWebCrawler and its methods
    with (
        patch("wet_mcp.sources.crawler.AsyncWebCrawler") as mock_crawler_class,
        patch("wet_mcp.sources.crawler._cleanup_browser_data_dir") as mock_cleanup,
    ):
        mock_instance = AsyncMock()
        mock_instance.__aenter__ = AsyncMock()
        mock_crawler_class.return_value = mock_instance

        # First attempt fails, second succeeds
        mock_instance.__aenter__.side_effect = [Exception("Startup failed"), None]

        # Reset singleton state
        crawler_mod._crawler_instance = None

        result = await _get_crawler(stealth=False)

        assert result == mock_instance
        assert mock_crawler_class.call_count == 2
        assert mock_cleanup.call_count == 1


@pytest.mark.asyncio
async def test_list_media_error_handling(mock_crawler_instance):
    """Test that list_media handles exceptions from crawler.arun."""
    mock_crawler_instance.arun = AsyncMock(side_effect=Exception("Media scan failed"))

    with patch(
        "wet_mcp.sources.crawler._get_crawler",
        new_callable=AsyncMock,
        return_value=mock_crawler_instance,
    ):
        result_json = await list_media(url="https://example.com")

    result = json.loads(result_json)
    assert "error" in result
    assert "Media scan failed" in result["error"]
