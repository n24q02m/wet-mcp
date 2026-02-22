import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from wet_mcp.sources.crawler import download_media


@pytest.mark.asyncio
async def test_download_media_streams_content():
    """Test that download_media uses streaming and does not load full content into memory."""
    mock_client = MagicMock()
    mock_client.get = AsyncMock()

    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.url = "http://example.com/large_file.mp4"
    mock_response.headers = {}
    mock_response.is_redirect = False

    # Mock content access to fail if called
    content_mock = MagicMock(
        side_effect=AssertionError("Should not access response.content")
    )
    type(mock_response).content = property(fget=content_mock)

    # Mock aiter_bytes
    async def mock_aiter_bytes():
        yield b"chunk1"
        yield b"chunk2"

    mock_response.aiter_bytes = mock_aiter_bytes

    # Mock stream context manager
    stream_ctx = MagicMock()
    stream_ctx.__aenter__.return_value = mock_response
    stream_ctx.__aexit__.return_value = None
    mock_client.stream.return_value = stream_ctx

    # Mock client context manager
    mock_client_cls = MagicMock()
    mock_client_cls.return_value.__aenter__.return_value = mock_client
    mock_client_cls.return_value.__aexit__.return_value = None

    with patch("httpx.AsyncClient", mock_client_cls):
        with (
            patch("pathlib.Path.mkdir"),
            patch("builtins.open", new_callable=MagicMock) as mock_open,
        ):
            mock_file = MagicMock()
            mock_open.return_value.__enter__.return_value = mock_file

            result_json = await download_media(
                ["http://example.com/large_file.mp4"], "/tmp/downloads"
            )

            # Verify stream was called
            mock_client.stream.assert_called()

            # Verify chunks were written
            mock_file.write.assert_any_call(b"chunk1")
            mock_file.write.assert_any_call(b"chunk2")

            # Verify result size
            results = json.loads(result_json)
            assert results[0]["size"] == 12  # len("chunk1") + len("chunk2")
