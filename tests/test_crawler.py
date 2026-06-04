import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from wet_mcp.sources.crawler import (
    _get_crawler,
    _get_scraping_agent,
    _get_semaphore,
    _is_document_url,
    batch_extract,
    convert_local_files,
    shutdown_crawler,
)


@pytest.mark.asyncio
async def test_get_semaphore():
    """Test lazy creation of browser semaphore."""
    with patch("wet_mcp.sources.crawler._browser_semaphore", None):
        sem = _get_semaphore()
        assert isinstance(sem, asyncio.Semaphore)
        assert sem._value == 6  # _MAX_CONCURRENT_OPS


@pytest.mark.asyncio
async def test_get_crawler_singleton():
    """Test that _get_crawler returns a singleton and handles stealth changes."""
    mock_crawler = MagicMock()
    mock_crawler.__aenter__ = AsyncMock(return_value=mock_crawler)
    mock_crawler.__aexit__ = AsyncMock(return_value=None)

    with (
        patch("wet_mcp.sources.crawler.AsyncWebCrawler", return_value=mock_crawler),
        patch("wet_mcp.sources.crawler._pool_lock", asyncio.Lock()),
        patch("wet_mcp.sources.crawler._crawler_instance", None),
        patch("wet_mcp.sources.crawler._crawler_stealth", False),
    ):
        # First call creates instance
        c1 = await _get_crawler(stealth=False)
        assert c1 is mock_crawler
        assert mock_crawler.__aenter__.call_count == 1

        # Second call with same stealth returns same instance
        c2 = await _get_crawler(stealth=False)
        assert c2 is c1
        assert mock_crawler.__aenter__.call_count == 1

        # Third call with different stealth recycles instance
        mock_crawler_stealth = MagicMock()
        mock_crawler_stealth.__aenter__ = AsyncMock(return_value=mock_crawler_stealth)
        mock_crawler_stealth.__aexit__ = AsyncMock(return_value=None)

        with patch(
            "wet_mcp.sources.crawler.AsyncWebCrawler", return_value=mock_crawler_stealth
        ):
            c3 = await _get_crawler(stealth=True)
            assert c3 is mock_crawler_stealth
            assert mock_crawler.__aexit__.call_count == 1
            assert mock_crawler_stealth.__aenter__.call_count == 1


@pytest.mark.asyncio
async def test_shutdown_crawler():
    """Test shutdown_crawler correctly cleans up."""
    mock_crawler = MagicMock()
    mock_crawler.__aexit__ = AsyncMock(return_value=None)

    with (
        patch("wet_mcp.sources.crawler._crawler_instance", mock_crawler),
        patch("wet_mcp.sources.crawler._pool_lock", asyncio.Lock()),
    ):
        await shutdown_crawler()
        mock_crawler.__aexit__.assert_called_once()
        from wet_mcp.sources.crawler import _crawler_instance

        assert _crawler_instance is None


@pytest.mark.asyncio
async def test_get_scraping_agent_singleton():
    """Test that _get_scraping_agent returns a singleton."""
    with (
        patch("wet_mcp.sources.crawler._scraping_agent", None),
        patch("wet_mcp.sources.crawler._agent_lock", asyncio.Lock()),
    ):
        agent1 = await _get_scraping_agent()
        agent2 = await _get_scraping_agent()
        assert agent1 is agent2


def test_is_document_url():
    """Test _is_document_url detection."""
    assert _is_document_url("https://example.com/file.pdf") is True
    assert _is_document_url("https://example.com/file.DOCX") is True
    assert _is_document_url("https://example.com/page.html") is False
    assert _is_document_url("https://example.com/image.png") is False


@pytest.mark.asyncio
async def test_batch_extract_validation():
    """Test batch_extract URL limit validation."""
    urls = ["http://example.com"] * 51
    result = await batch_extract(urls)
    assert "Error: Maximum 50 URLs per batch" in result


@pytest.mark.asyncio
async def test_convert_local_files_validation():
    """Test convert_local_files path limit validation."""
    paths = ["/tmp/file.txt"] * 11
    result = await convert_local_files(paths)
    assert "Error: Maximum 10 files per call" in result
