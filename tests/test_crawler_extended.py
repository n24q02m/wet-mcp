"""Extended unit tests for crawl functionality."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from wet_mcp.sources.crawler import crawl


@pytest.mark.asyncio
async def test_crawl_format_html(mock_crawler_instance):
    """Test that format='html' returns cleaned_html."""
    mock_result = MagicMock()
    mock_result.success = True
    mock_result.markdown = "Markdown Content"
    mock_result.cleaned_html = "<p>HTML Content</p>"
    mock_result.metadata = {"title": "Mock Title"}
    mock_result.links = {"internal": [], "external": []}

    mock_crawler_instance.arun = AsyncMock(return_value=mock_result)

    with patch(
        "wet_mcp.sources.crawler._get_crawler",
        new_callable=AsyncMock,
        return_value=mock_crawler_instance,
    ):
        result_json = await crawl(
            urls=["https://example.com"],
            format="html",
            depth=1,
            max_pages=10
        )

    results = json.loads(result_json)
    assert len(results) == 1
    assert results[0]["content"] == "<p>HTML Content</p>"


@pytest.mark.asyncio
async def test_crawl_internal_links_limit(mock_crawler_instance):
    """Test that only the first 10 internal links are queued."""

    # Generate 15 internal links
    internal_links = [{"href": f"https://example.com/page{i}"} for i in range(1, 16)]

    mock_result_root = MagicMock()
    mock_result_root.success = True
    mock_result_root.markdown = "Root Content"
    mock_result_root.cleaned_html = "<p>Root</p>"
    mock_result_root.metadata = {"title": "Root"}
    mock_result_root.links = {"internal": internal_links, "external": []}

    # Mock subsequent calls to return no links to stop recursion
    mock_result_leaf = MagicMock()
    mock_result_leaf.success = True
    mock_result_leaf.markdown = "Leaf Content"
    mock_result_leaf.cleaned_html = "<p>Leaf</p>"
    mock_result_leaf.metadata = {"title": "Leaf"}
    mock_result_leaf.links = {"internal": [], "external": []}

    def side_effect(url, config=None):
        if url == "https://example.com":
            return mock_result_root
        return mock_result_leaf

    mock_crawler_instance.arun = AsyncMock(side_effect=side_effect)

    with patch(
        "wet_mcp.sources.crawler._get_crawler",
        new_callable=AsyncMock,
        return_value=mock_crawler_instance,
    ):
        # Set max_pages high enough to cover root + 10 children
        result_json = await crawl(
            urls=["https://example.com"],
            depth=2,
            max_pages=20
        )

    results = json.loads(result_json)

    # Expect 1 root + 10 children = 11 pages
    assert len(results) == 11

    urls = sorted([r["url"] for r in results])
    expected_urls = sorted(
        ["https://example.com"] +
        [f"https://example.com/page{i}" for i in range(1, 11)]
    )
    assert urls == expected_urls

    # Verify page 11 (the 11th link) was NOT crawled
    assert "https://example.com/page11" not in [r["url"] for r in results]


@pytest.mark.asyncio
async def test_crawl_links_as_strings(mock_crawler_instance):
    """Test that links returned as strings (not dicts) are handled correctly."""

    def side_effect(url, config=None):
        res = MagicMock()
        res.success = True
        res.markdown = f"Content for {url}"
        res.cleaned_html = f"<p>Content for {url}</p>"
        res.metadata = {"title": f"Title for {url}"}

        if url == "https://example.com":
             # Return list of strings here
             res.links = {"internal": ["https://example.com/page2"], "external": []}
        else:
             res.links = {"internal": [], "external": []}
        return res

    mock_crawler_instance.arun = AsyncMock(side_effect=side_effect)

    with patch(
        "wet_mcp.sources.crawler._get_crawler",
        new_callable=AsyncMock,
        return_value=mock_crawler_instance,
    ):
        result_json = await crawl(
            urls=["https://example.com"],
            depth=2,
            max_pages=10
        )

    results = json.loads(result_json)
    assert len(results) == 2
    assert "https://example.com/page2" in [r["url"] for r in results]


@pytest.mark.asyncio
async def test_crawl_unicode_content(mock_crawler_instance):
    """Test that unicode content is preserved in JSON output."""
    unicode_content = "Hello 🌍 世界"
    mock_result = MagicMock()
    mock_result.success = True
    mock_result.markdown = unicode_content
    mock_result.cleaned_html = f"<p>{unicode_content}</p>"
    mock_result.metadata = {"title": "Unicode Title 🚀"}
    mock_result.links = {"internal": [], "external": []}

    mock_crawler_instance.arun = AsyncMock(return_value=mock_result)

    with patch(
        "wet_mcp.sources.crawler._get_crawler",
        new_callable=AsyncMock,
        return_value=mock_crawler_instance,
    ):
        result_json = await crawl(urls=["https://example.com"])

    # Verify JSON string contains actual unicode chars, not escaped \uXXXX
    # because ensure_ascii=False is used
    assert "🌍" in result_json
    assert "世界" in result_json

    results = json.loads(result_json)
    assert results[0]["content"] == unicode_content
    assert results[0]["title"] == "Unicode Title 🚀"
