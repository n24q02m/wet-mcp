from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from wet_mcp.sources.crawler import download_media


@pytest.mark.asyncio
async def test_download_media_path_traversal(tmp_path):
    """Test that download_media prevents path traversal."""

    # Mock stream response
    mock_response = AsyncMock()
    mock_response.raise_for_status = MagicMock()

    # Mock stream context manager
    mock_stream_ctx = MagicMock()
    mock_stream_ctx.__aenter__.return_value = mock_response
    mock_stream_ctx.__aexit__.return_value = None

    # Mock httpx client
    mock_client = AsyncMock()
    mock_client.stream = MagicMock(return_value=mock_stream_ctx)

    # Mock client constructor
    mock_client_cls = MagicMock()
    mock_client_cls.return_value.__aenter__.return_value = mock_client
    mock_client_cls.return_value.__aexit__.return_value = None

    with patch("wet_mcp.sources.crawler.is_safe_url", return_value=True):
        with patch("httpx.AsyncClient", mock_client_cls):
            with patch("builtins.open"):  # Prevent file write attempt
                # 1. Traversal attempt with '..' as filename
                url1 = "http://example.com/.."
                res1 = await download_media([url1], str(tmp_path))

                # Should fail with "Security Alert" because '..' resolves to parent dir
                assert "Security Alert" in res1

                # Verify stream was called (since is_safe_url=True) but processing failed due to path check
                mock_client.stream.assert_called()


@pytest.mark.asyncio
async def test_download_media_safe(tmp_path):
    # Mock response
    mock_response = AsyncMock()
    mock_response.raise_for_status = MagicMock()

    # Mock aiter_bytes
    async def async_iter():
        yield b"safe "
        yield b"content"

    mock_response.aiter_bytes = async_iter

    # Mock stream context manager
    mock_stream_ctx = MagicMock()
    mock_stream_ctx.__aenter__.return_value = mock_response
    mock_stream_ctx.__aexit__.return_value = None

    # Mock client
    mock_client = AsyncMock()
    mock_client.stream = MagicMock(return_value=mock_stream_ctx)

    # Mock client constructor
    mock_client_cls = MagicMock()
    mock_client_cls.return_value.__aenter__.return_value = mock_client
    mock_client_cls.return_value.__aexit__.return_value = None

    with patch("wet_mcp.sources.crawler.is_safe_url", return_value=True):
        with patch("httpx.AsyncClient", mock_client_cls):
            # We don't patch open because we want to test actual write (to tmp_path)

            url = "http://example.com/image.png"
            await download_media([url], str(tmp_path))

            expected_file = tmp_path / "image.png"
            assert expected_file.exists()
            assert expected_file.read_bytes() == b"safe content"
