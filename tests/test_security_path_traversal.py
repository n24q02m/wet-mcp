from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from wet_mcp.sources.crawler import download_media


@pytest.mark.asyncio
async def test_download_media_path_traversal(tmp_path):
    """Test that download_media prevents path traversal."""

    # Mock httpx response
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()

    # Mock httpx client
    mock_client = AsyncMock()

    # stream returns a context manager
    mock_stream_ctx = MagicMock()
    mock_stream_ctx.__aenter__ = AsyncMock(return_value=mock_response)
    mock_stream_ctx.__aexit__ = AsyncMock(return_value=None)
    mock_client.stream = MagicMock(return_value=mock_stream_ctx)

    # client context manager
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

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
    mock_response.raise_for_status = MagicMock()

    async def mock_aiter_bytes(chunk_size=None):
        yield b"safe "
        yield b"content"

    mock_response.aiter_bytes = mock_aiter_bytes

    mock_stream_ctx = MagicMock()
    mock_stream_ctx.__aenter__ = AsyncMock(return_value=mock_response)
    mock_stream_ctx.__aexit__ = AsyncMock(return_value=None)

    mock_client = AsyncMock()
    mock_client.stream = MagicMock(return_value=mock_stream_ctx)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with patch("wet_mcp.sources.crawler.is_safe_url", return_value=True):
        with patch("httpx.AsyncClient", return_value=mock_client):
            url = "http://example.com/image.png"
            await download_media([url], str(tmp_path))

            expected_file = tmp_path / "image.png"
            assert expected_file.exists()
            assert expected_file.read_bytes() == b"safe content"
