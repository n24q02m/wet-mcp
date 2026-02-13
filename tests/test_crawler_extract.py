"""Tests for extract functionality with singleton browser pool."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from wet_mcp.sources.crawler import extract


@pytest.mark.asyncio
async def test_extract_success(mock_crawler_instance):
    """Test successful content extraction."""
    mock_result = MagicMock()
    mock_result.success = True
    mock_result.markdown = "# Test Title\n\nTest content."
    mock_result.cleaned_html = "<h1>Test Title</h1><p>Test content.</p>"
    mock_result.metadata = {"title": "Test Page"}
    mock_result.links = {"internal": ["/about"], "external": ["https://google.com"]}
    mock_result.error_message = None

    mock_crawler_instance.arun = AsyncMock(return_value=mock_result)

    with patch(
        "wet_mcp.sources.crawler._get_crawler",
        new_callable=AsyncMock,
        return_value=mock_crawler_instance,
    ):
        result_json = await extract(["https://example.com"], format="markdown")
        results = json.loads(result_json)

        assert len(results) == 1
        assert results[0]["url"] == "https://example.com"
        assert results[0]["title"] == "Test Page"
        assert results[0]["content"] == "# Test Title\n\nTest content."
        assert results[0]["links"]["internal"] == ["/about"]
        assert results[0]["links"]["external"] == ["https://google.com"]


@pytest.mark.asyncio
async def test_extract_failure(mock_crawler_instance):
    """Test failed content extraction."""
    mock_result = MagicMock()
    mock_result.success = False
    mock_result.error_message = "Page not found"

    mock_crawler_instance.arun = AsyncMock(return_value=mock_result)

    with patch(
        "wet_mcp.sources.crawler._get_crawler",
        new_callable=AsyncMock,
        return_value=mock_crawler_instance,
    ):
        result_json = await extract(["https://example.com"])
        results = json.loads(result_json)

        assert len(results) == 1
        assert results[0]["url"] == "https://example.com"
        assert results[0]["error"] == "Page not found"


@pytest.mark.asyncio
async def test_extract_unsafe_url(mock_crawler_instance):
    """Test extraction with unsafe URL."""
    mock_crawler_instance.arun = AsyncMock()

    with patch(
        "wet_mcp.sources.crawler._get_crawler",
        new_callable=AsyncMock,
        return_value=mock_crawler_instance,
    ):
        result_json = await extract(["http://127.0.0.1"])
        results = json.loads(result_json)

        assert len(results) == 1
        assert results[0]["url"] == "http://127.0.0.1"
        assert "Security Alert" in results[0]["error"]

        mock_crawler_instance.arun.assert_not_called()


@pytest.mark.asyncio
async def test_extract_exception(mock_crawler_instance):
    """Test extraction when crawler raises exception."""
    mock_crawler_instance.arun = AsyncMock(side_effect=Exception("Connection error"))

    with patch(
        "wet_mcp.sources.crawler._get_crawler",
        new_callable=AsyncMock,
        return_value=mock_crawler_instance,
    ):
        result_json = await extract(["https://example.com"])
        results = json.loads(result_json)

        assert len(results) == 1
        assert results[0]["url"] == "https://example.com"
        assert "Connection error" in results[0]["error"]


@pytest.mark.asyncio
async def test_extract_html_format(mock_crawler_instance):
    """Test extraction with HTML format."""
    mock_result = MagicMock()
    mock_result.success = True
    mock_result.markdown = "Markdown"
    mock_result.cleaned_html = "<p>HTML</p>"
    mock_result.metadata = {"title": "Test"}
    mock_result.links = {}

    mock_crawler_instance.arun = AsyncMock(return_value=mock_result)

    with patch(
        "wet_mcp.sources.crawler._get_crawler",
        new_callable=AsyncMock,
        return_value=mock_crawler_instance,
    ):
        result_json = await extract(["https://example.com"], format="html")
        results = json.loads(result_json)

        assert results[0]["content"] == "<p>HTML</p>"


@pytest.mark.asyncio
async def test_extract_stealth_param(mock_crawler_instance):
    """Test stealth parameter is passed to _get_crawler."""
    mock_result = MagicMock()
    mock_result.success = True
    mock_result.markdown = "content"
    mock_result.metadata = {}
    mock_result.links = {}
    mock_result.cleaned_html = "<p>content</p>"

    mock_crawler_instance.arun = AsyncMock(return_value=mock_result)

    with patch(
        "wet_mcp.sources.crawler._get_crawler",
        new_callable=AsyncMock,
        return_value=mock_crawler_instance,
    ) as mock_get_crawler:
        # Test with stealth=True
        await extract(["https://example.com"], stealth=True)
        mock_get_crawler.assert_called_with(True)

        mock_get_crawler.reset_mock()

        # Test with stealth=False
        await extract(["https://example.com"], stealth=False)
        mock_get_crawler.assert_called_with(False)


@pytest.mark.asyncio
async def test_extract_empty_list(mock_crawler_instance):
    """Test extraction with empty URL list."""
    mock_crawler_instance.arun = AsyncMock()

    with patch(
        "wet_mcp.sources.crawler._get_crawler",
        new_callable=AsyncMock,
        return_value=mock_crawler_instance,
    ):
        result_json = await extract([])
        results = json.loads(result_json)

        assert results == []
        mock_crawler_instance.arun.assert_not_called()


@pytest.mark.asyncio
async def test_extract_mixed_results(mock_crawler_instance):
    """Test extraction with mixed success and failure results."""

    def side_effect(url, config=None):
        result = MagicMock()
        if url == "https://good.com":
            result.success = True
            result.markdown = "Good content"
            result.cleaned_html = "<p>Good content</p>"
            result.metadata = {"title": "Good Page"}
            result.links = {"internal": [], "external": []}
        else:
            result.success = False
            result.error_message = "Failed"
        return result

    mock_crawler_instance.arun = AsyncMock(side_effect=side_effect)

    with patch(
        "wet_mcp.sources.crawler._get_crawler",
        new_callable=AsyncMock,
        return_value=mock_crawler_instance,
    ):
        result_json = await extract(["https://good.com", "https://bad.com"])
        results = json.loads(result_json)

        assert len(results) == 2
        # Sort results by URL to ensure deterministic assertions
        results.sort(key=lambda x: x["url"])

        assert results[0]["url"] == "https://bad.com"
        assert results[0]["error"] == "Failed"

        assert results[1]["url"] == "https://good.com"
        assert results[1]["content"] == "Good content"


@pytest.mark.asyncio
async def test_extract_malformed_links(mock_crawler_instance):
    """Test robustness against malformed crawler results (links is None)."""
    mock_result = MagicMock()
    mock_result.success = True
    mock_result.markdown = "Content"
    mock_result.cleaned_html = "<p>Content</p>"
    mock_result.metadata = {"title": "Title"}
    mock_result.links = None  # Simulating malformed response

    mock_crawler_instance.arun = AsyncMock(return_value=mock_result)

    with patch(
        "wet_mcp.sources.crawler._get_crawler",
        new_callable=AsyncMock,
        return_value=mock_crawler_instance,
    ):
        result_json = await extract(["https://example.com"])
        results = json.loads(result_json)

        assert len(results) == 1
        assert "error" in results[0]
        assert "NoneType" in results[0]["error"]


@pytest.mark.asyncio
async def test_extract_crawler_init_failure():
    """Test that crawler initialization failure propagates."""
    with patch(
        "wet_mcp.sources.crawler._get_crawler",
        side_effect=Exception("Init failed"),
    ):
        with pytest.raises(Exception, match="Init failed"):
            await extract(["https://example.com"])
