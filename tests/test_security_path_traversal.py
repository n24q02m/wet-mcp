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
    mock_response.is_redirect = False  # Important for manual redirect loop

    # Mock httpx client context manager
    mock_client = AsyncMock()
    mock_client.get.return_value = mock_response
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = None

    with patch("wet_mcp.sources.crawler.is_safe_url", return_value=True):
        with patch(
            "wet_mcp.sources.crawler.httpx.AsyncClient", return_value=mock_client
        ):
            # 1. Traversal attempt with '..' as filename
            # This simulates a URL where split('/')[-1] is '..'
            url1 = "http://example.com/.."
            res1 = await download_media([url1], str(tmp_path))

            # Should fail with "Security Alert" because '..' resolves to parent dir
            assert "Security Alert" in res1

            # Verify no files were written in parent
            pass


@pytest.mark.asyncio
async def test_download_media_safe(tmp_path):
    mock_response = MagicMock()
    mock_response.content = b"safe content"
    mock_response.raise_for_status = MagicMock()
    mock_response.is_redirect = False  # Important for manual redirect loop

    mock_client = AsyncMock()
    mock_client.get.return_value = mock_response
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = None

    with patch("wet_mcp.sources.crawler.is_safe_url", return_value=True):
        with patch(
            "wet_mcp.sources.crawler.httpx.AsyncClient", return_value=mock_client
        ):
            url = "http://example.com/image.png"
            await download_media([url], str(tmp_path))

            expected_file = tmp_path / "image.png"
            assert expected_file.exists()
            assert expected_file.read_bytes() == b"safe content"

@pytest.mark.asyncio
async def test_download_media_path_traversal_urlencode(tmp_path):
    mock_response = MagicMock()
    mock_response.content = b"fake content"
    mock_response.raise_for_status = MagicMock()
    mock_response.is_redirect = False

    mock_client = AsyncMock()
    mock_client.get.return_value = mock_response
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = None

    with patch("wet_mcp.sources.crawler.is_safe_url", return_value=True):
        with patch("wet_mcp.sources.crawler.httpx.AsyncClient", return_value=mock_client):
            # Traversal attempt with URL-encoded '../' as filename
            url1 = "http://example.com/..%2f..%2f..%2fetc%2fpasswd"
            res1 = await download_media([url1], str(tmp_path))

            # Our fix now safely resolves the filename to 'passwd' and prevents path traversal
            # Verify that the filename was correctly safely resolved to 'passwd' inside the output path
            assert "passwd" in res1
            assert "Security Alert" not in res1

            expected_file = tmp_path / "passwd"
            assert expected_file.exists()
            assert expected_file.read_bytes() == b"fake content"
