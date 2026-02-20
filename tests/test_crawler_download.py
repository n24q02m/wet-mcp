import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from wet_mcp.sources.crawler import download_media


@pytest.mark.asyncio
async def test_download_media_success_streaming():
    # Mock httpx.AsyncClient
    mock_client = AsyncMock()
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()

    # Mock streaming response
    async def mock_aiter_bytes():
        yield b"fake "
        yield b"image "
        yield b"content"

    mock_response.aiter_bytes = mock_aiter_bytes

    # Mock stream context manager
    mock_stream_ctx = AsyncMock()
    mock_stream_ctx.__aenter__.return_value = mock_response
    mock_stream_ctx.__aexit__.return_value = None

    # client.stream is a sync method returning an async context manager
    mock_client.stream = MagicMock(return_value=mock_stream_ctx)

    # Mock context manager for AsyncClient
    mock_client_cm = AsyncMock()
    mock_client_cm.__aenter__.return_value = mock_client
    mock_client_cm.__aexit__.return_value = None

    with patch("httpx.AsyncClient", return_value=mock_client_cm):
        with patch("pathlib.Path.mkdir"):
            # Mock file writing
            mock_file = MagicMock()
            mock_file.__enter__.return_value = mock_file
            mock_file.__exit__.return_value = None

            with patch("builtins.open", return_value=mock_file) as mock_open:
                 with patch("wet_mcp.sources.crawler.is_safe_url", return_value=True):
                    result_json = await download_media(
                        media_urls=["https://example.com/image.png"],
                        output_dir="/tmp/downloads"
                    )

    results = json.loads(result_json)
    assert len(results) == 1
    assert results[0]["url"] == "https://example.com/image.png"
    assert "path" in results[0]
    assert results[0]["size"] == len(b"fake image content")

    # Verify stream was called
    mock_client.stream.assert_called_with("GET", "https://example.com/image.png", follow_redirects=True)

    # Verify file writes
    mock_open.assert_called()
    assert mock_file.write.call_count == 3
    mock_file.write.assert_any_call(b"fake ")
    mock_file.write.assert_any_call(b"image ")
    mock_file.write.assert_any_call(b"content")
