import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from wet_mcp.sources.crawler import extract


@pytest.mark.asyncio
async def test_extract_success():
    """Test successful content extraction."""
    mock_result = MagicMock()
    mock_result.success = True
    mock_result.markdown = "# Test Title\n\nTest content."
    mock_result.cleaned_html = "<h1>Test Title</h1><p>Test content.</p>"
    mock_result.metadata = {"title": "Test Page"}
    mock_result.links = {"internal": ["/about"], "external": ["https://google.com"]}
    mock_result.error_message = None

    with patch("wet_mcp.sources.crawler.AsyncWebCrawler") as MockCrawler:
        mock_crawler_instance = MockCrawler.return_value
        mock_crawler_instance.__aenter__.return_value = mock_crawler_instance
        mock_crawler_instance.arun = AsyncMock(return_value=mock_result)

        result_json = await extract(["https://example.com"], format="markdown")
        results = json.loads(result_json)

        assert len(results) == 1
        assert results[0]["url"] == "https://example.com"
        assert results[0]["title"] == "Test Page"
        assert results[0]["content"] == "# Test Title\n\nTest content."
        assert results[0]["links"]["internal"] == ["/about"]
        assert results[0]["links"]["external"] == ["https://google.com"]


@pytest.mark.asyncio
async def test_extract_failure():
    """Test failed content extraction."""
    mock_result = MagicMock()
    mock_result.success = False
    mock_result.error_message = "Page not found"

    with patch("wet_mcp.sources.crawler.AsyncWebCrawler") as MockCrawler:
        mock_crawler_instance = MockCrawler.return_value
        mock_crawler_instance.__aenter__.return_value = mock_crawler_instance
        mock_crawler_instance.arun = AsyncMock(return_value=mock_result)

        result_json = await extract(["https://example.com"])
        results = json.loads(result_json)

        assert len(results) == 1
        assert results[0]["url"] == "https://example.com"
        assert results[0]["error"] == "Page not found"


@pytest.mark.asyncio
async def test_extract_unsafe_url():
    """Test extraction with unsafe URL."""
    with patch("wet_mcp.sources.crawler.AsyncWebCrawler") as MockCrawler:
        mock_crawler_instance = MockCrawler.return_value
        mock_crawler_instance.__aenter__.return_value = mock_crawler_instance

        result_json = await extract(["http://127.0.0.1"])
        results = json.loads(result_json)

        assert len(results) == 1
        assert results[0]["url"] == "http://127.0.0.1"
        assert "Security Alert" in results[0]["error"]

        mock_crawler_instance.arun.assert_not_called()


@pytest.mark.asyncio
async def test_extract_exception():
    """Test extraction when crawler raises exception."""
    with patch("wet_mcp.sources.crawler.AsyncWebCrawler") as MockCrawler:
        mock_crawler_instance = MockCrawler.return_value
        mock_crawler_instance.__aenter__.return_value = mock_crawler_instance
        mock_crawler_instance.arun = AsyncMock(
            side_effect=Exception("Connection error")
        )

        result_json = await extract(["https://example.com"])
        results = json.loads(result_json)

        assert len(results) == 1
        assert results[0]["url"] == "https://example.com"
        assert "Connection error" in results[0]["error"]


@pytest.mark.asyncio
async def test_extract_html_format():
    """Test extraction with HTML format."""
    mock_result = MagicMock()
    mock_result.success = True
    mock_result.markdown = "Markdown"
    mock_result.cleaned_html = "<p>HTML</p>"
    mock_result.metadata = {"title": "Test"}
    mock_result.links = {}

    with patch("wet_mcp.sources.crawler.AsyncWebCrawler") as MockCrawler:
        mock_crawler_instance = MockCrawler.return_value
        mock_crawler_instance.__aenter__.return_value = mock_crawler_instance
        mock_crawler_instance.arun = AsyncMock(return_value=mock_result)

        result_json = await extract(["https://example.com"], format="html")
        results = json.loads(result_json)

        assert results[0]["content"] == "<p>HTML</p>"


@pytest.mark.asyncio
async def test_extract_stealth_param():
    """Test stealth parameter is passed to browser config."""
    mock_result = MagicMock()
    mock_result.success = True
    mock_result.markdown = "content"
    mock_result.metadata = {}
    mock_result.links = {}
    mock_result.cleaned_html = "<p>content</p>"

    with patch("wet_mcp.sources.crawler.AsyncWebCrawler") as MockCrawler:
        mock_crawler_instance = MockCrawler.return_value
        mock_crawler_instance.__aenter__.return_value = mock_crawler_instance
        mock_crawler_instance.arun = AsyncMock(return_value=mock_result)

        # Test with stealth=True
        await extract(["https://example.com"], stealth=True)

        args, kwargs = MockCrawler.call_args_list[0]
        config = kwargs.get("config")
        assert config.enable_stealth is True

        # Test with stealth=False
        await extract(["https://example.com"], stealth=False)

        args, kwargs = MockCrawler.call_args_list[1]
        config = kwargs.get("config")
        assert config.enable_stealth is False


@pytest.mark.asyncio
async def test_extract_empty_list():
    """Test extraction with empty URL list."""
    with patch("wet_mcp.sources.crawler.AsyncWebCrawler") as MockCrawler:
        mock_crawler_instance = MockCrawler.return_value
        mock_crawler_instance.__aenter__.return_value = mock_crawler_instance

        result_json = await extract([])
        results = json.loads(result_json)

        assert results == []
        MockCrawler.assert_called_once()
        mock_crawler_instance.arun.assert_not_called()
