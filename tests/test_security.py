"""Security integration tests for crawler tools."""

from unittest.mock import AsyncMock, patch

import pytest

from wet_mcp.sources.crawler import (
    crawl,
    download_media,
    extract,
    list_media,
    sitemap,
)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "tool_func, kwargs, expected_substr",
    [
        (
            crawl,
            {"urls": ["https://unsafe.com"], "depth": 0, "max_pages": 1},
            "[]",
        ),
        (
            download_media,
            {"media_urls": ["https://unsafe.com"], "output_dir": "/tmp"},
            "Security Alert",
        ),
        (
            extract,
            {"urls": ["https://unsafe.com"]},
            "Security Alert",
        ),
        (
            list_media,
            {"url": "https://unsafe.com"},
            "Security Alert",
        ),
        (
            sitemap,
            {"urls": ["https://unsafe.com"], "depth": 0},
            "[]",
        ),
    ],
    ids=["crawl", "download_media", "extract", "list_media", "sitemap"],
)
async def test_crawler_tools_reject_unsafe_urls(tool_func, kwargs, expected_substr):
    """Verify that all crawler tools reject unsafe URLs based on is_safe_url check."""
    # Mock is_safe_url to return False (unsafe)
    with patch(
        "wet_mcp.sources.crawler.is_safe_url", return_value=False
    ) as mock_is_safe:
        # Also mock _get_crawler to ensure no browser is launched if the check fails
        # (This is a safety net; the code should return early)
        with patch(
            "wet_mcp.sources.crawler._get_crawler", new_callable=AsyncMock
        ) as mock_get_crawler:
            # Mock filesystem operations for download_media to prevent side effects
            with patch("pathlib.Path.mkdir"), patch("pathlib.Path.write_bytes"):
                result = await tool_func(**kwargs)

    # Verify is_safe_url was called at least once
    assert mock_is_safe.called

    # For list_media (single URL), _get_crawler should check BEFORE init, so it shouldn't be called.
    if tool_func == list_media:
        mock_get_crawler.assert_not_called()

    # For others (list of URLs), _get_crawler might be called, but arun should NOT be called.
    if tool_func in [crawl, extract, sitemap]:
        # The mock_get_crawler is the function. Its return value is the crawler instance.
        crawler_instance = mock_get_crawler.return_value
        crawler_instance.arun.assert_not_called()

    # Verify result format
    assert isinstance(result, str)

    if expected_substr == "[]":
        # crawl and sitemap return empty list for unsafe URLs
        assert result == "[]"
    else:
        # others return JSON with error message
        assert expected_substr in result
