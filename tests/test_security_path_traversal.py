from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from wet_mcp.sources.crawler import download_media


@pytest.mark.asyncio
async def test_download_media_path_traversal(tmp_path):
    """Test that download_media prevents path traversal."""

    # Mock httpx response
    mock_response = MagicMock()
    mock_response.content = b"fake content"
    mock_response.raise_for_status = MagicMock()

    # Mock httpx client context manager
    mock_client = AsyncMock()
    mock_client.get.return_value = mock_response
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = None

    # We need to simulate is_safe_url passing for these URLs, or mock it.
    # Since we are testing path traversal, we assume the URL is "safe" network-wise but malicious filename-wise.
    # But wait, is_safe_url checks scheme and IP.
    # "http://example.com/.." is safe network-wise (resolves to example.com IP).

    with patch("wet_mcp.sources.crawler.is_safe_url", return_value=True):
        with patch("httpx.AsyncClient", return_value=mock_client):
            # 1. Traversal attempt with '..' as filename
            # url.split('/')[-1] is '..'
            url1 = "http://example.com/.."
            res1 = await download_media([url1], str(tmp_path))
            assert "Security Alert" in res1 or "error" in res1

            # Verify file was NOT written to parent
            assert not (tmp_path.parent / "content").exists() # Just sanity check

            # 2. Traversal attempt with encoded characters?
            # url.split('/')[-1] is naive.
            # If we use a filename that results in traversal?
            # Current fix checks: filename in ('.', '..') -> becomes "download".
            # And filepath.resolve().relative_to(...)

            # Let's try to mock writing to a file that WOULD fail the relative_to check if it weren't caught.
            # But we can't easily force filename to be 'subdir/../outside' via split('/').

            # However, testing '..' is good enough as it's the main vector if split('/') is used.
            pass

@pytest.mark.asyncio
async def test_download_media_safe(tmp_path):
    mock_response = MagicMock()
    mock_response.content = b"safe content"
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.get.return_value = mock_response
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = None

    with patch("wet_mcp.sources.crawler.is_safe_url", return_value=True):
        with patch("httpx.AsyncClient", return_value=mock_client):
            url = "http://example.com/image.png"
            await download_media([url], str(tmp_path))

            expected_file = tmp_path / "image.png"
            assert expected_file.exists()
            assert expected_file.read_bytes() == b"safe content"
