from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from wet_mcp.config import Settings
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

    # Allow tmp_path as download dir
    test_settings = Settings(download_dir=str(tmp_path))

    with patch("wet_mcp.sources.crawler.settings", test_settings):
        with patch("wet_mcp.sources.crawler.is_safe_url", return_value=True):
            with patch("httpx.AsyncClient", return_value=mock_client):
                # 1. Traversal attempt with '..' as filename
                url1 = "http://example.com/.."
                res1 = await download_media([url1], str(tmp_path))

                # Should fail with "Security Alert" because '..' resolves to parent dir
                assert "Security Alert" in res1


@pytest.mark.asyncio
async def test_download_media_safe(tmp_path):
    mock_response = MagicMock()
    mock_response.content = b"safe content"
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.get.return_value = mock_response
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = None

    # Allow tmp_path as download dir
    test_settings = Settings(download_dir=str(tmp_path))

    with patch("wet_mcp.sources.crawler.settings", test_settings):
        with patch("wet_mcp.sources.crawler.is_safe_url", return_value=True):
            with patch("httpx.AsyncClient", return_value=mock_client):
                url = "http://example.com/image.png"
                await download_media([url], str(tmp_path))

                expected_file = tmp_path / "image.png"
                assert expected_file.exists()
                assert expected_file.read_bytes() == b"safe content"
