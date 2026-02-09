import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from wet_mcp.sources.crawler import download_media, extract, crawl, sitemap, list_media

@pytest.mark.asyncio
async def test_download_media_blocks_unsafe_urls(tmp_path):
    """Test that download_media checks is_safe_url before downloading."""
    unsafe_url = "http://127.0.0.1/secret.txt"

    # Mock httpx client to ensure no real network calls
    mock_response = MagicMock()
    mock_response.content = b"secret content"
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.get.return_value = mock_response
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = None

    with patch("httpx.AsyncClient", return_value=mock_client):
        # We patch is_safe_url to verify it's called and respected.
        # Since the URL is 127.0.0.1, real is_safe_url returns False.
        # But we can also force it to False to be sure.
        with patch("wet_mcp.sources.crawler.is_safe_url", return_value=False) as mock_is_safe:

            results_json = await download_media([unsafe_url], str(tmp_path))

            # If safe, it should NOT download
            assert not mock_client.get.called, "download_media should not call httpx.get for unsafe URLs"
            assert mock_is_safe.called, "download_media should call is_safe_url"

            # Check results for error
            assert "Security Alert" in results_json or "Unsafe URL" in results_json or "error" in results_json

@pytest.mark.asyncio
async def test_extract_blocks_unsafe_urls():
    """Test that extract checks is_safe_url."""
    unsafe_url = "http://127.0.0.1/secret.html"

    with patch("wet_mcp.sources.crawler.AsyncWebCrawler") as MockCrawler:
        mock_instance = MockCrawler.return_value
        mock_instance.__aenter__.return_value = mock_instance
        mock_instance.__aexit__.return_value = None

        with patch("wet_mcp.sources.crawler.is_safe_url", return_value=False) as mock_is_safe:
            await extract([unsafe_url])

            assert mock_is_safe.called
            # crawler.arun should NOT be called for unsafe URL
            assert not mock_instance.arun.called

@pytest.mark.asyncio
async def test_crawl_blocks_unsafe_urls():
    """Test that crawl checks is_safe_url."""
    unsafe_url = "http://127.0.0.1/"

    with patch("wet_mcp.sources.crawler.AsyncWebCrawler") as MockCrawler:
        mock_instance = MockCrawler.return_value
        mock_instance.__aenter__.return_value = mock_instance
        mock_instance.__aexit__.return_value = None

        with patch("wet_mcp.sources.crawler.is_safe_url", return_value=False) as mock_is_safe:
            await crawl([unsafe_url])

            assert mock_is_safe.called
            assert not mock_instance.arun.called

@pytest.mark.asyncio
async def test_sitemap_blocks_unsafe_urls():
    """Test that sitemap blocks unsafe URLs."""
    unsafe_url = "http://127.0.0.1/"

    with patch("wet_mcp.sources.crawler.AsyncWebCrawler") as MockCrawler:
        mock_instance = MockCrawler.return_value
        mock_instance.__aenter__.return_value = mock_instance
        mock_instance.__aexit__.return_value = None

        with patch("wet_mcp.sources.crawler.is_safe_url", return_value=False) as mock_is_safe:
            await sitemap([unsafe_url])

            assert mock_is_safe.called
            assert not mock_instance.arun.called

@pytest.mark.asyncio
async def test_list_media_blocks_unsafe_urls():
    """Test that list_media blocks unsafe URLs."""
    unsafe_url = "http://127.0.0.1/"

    with patch("wet_mcp.sources.crawler.AsyncWebCrawler") as MockCrawler:
        mock_instance = MockCrawler.return_value
        mock_instance.__aenter__.return_value = mock_instance
        mock_instance.__aexit__.return_value = None

        with patch("wet_mcp.sources.crawler.is_safe_url", return_value=False) as mock_is_safe:
            await list_media(unsafe_url)

            assert mock_is_safe.called
            assert not mock_instance.arun.called
