import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from wet_mcp.sources.crawler import download_media


@pytest.mark.asyncio
async def test_download_media_streams_content():
    """Test that download_media uses streaming to download content."""

    # Mock response
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.url = "http://example.com/file.jpg"

    # Mock aiter_bytes to return chunks
    async def async_iter():
        yield b"chunk1"
        yield b"chunk2"

    mock_response.aiter_bytes = MagicMock(return_value=async_iter())

    # Mock client.stream context manager
    # client.stream() returns an async context manager
    mock_client = AsyncMock()
    mock_client.stream = MagicMock()
    mock_stream_ctx = AsyncMock()
    mock_stream_ctx.__aenter__.return_value = mock_response
    mock_stream_ctx.__aexit__.return_value = None
    mock_client.stream.return_value = mock_stream_ctx

    # Mock client constructor context manager
    mock_client_cls = MagicMock()
    mock_client_instance = mock_client
    mock_client_ctx = AsyncMock()
    mock_client_ctx.__aenter__.return_value = mock_client_instance
    mock_client_ctx.__aexit__.return_value = None
    mock_client_cls.return_value = mock_client_ctx

    # We need to mock open() to verify writes
    # But builtins.open is hard to patch when used in a thread if strictly separate?
    # Actually, asyncio.to_thread just runs the function in a separate thread.
    # If we pass a mock object's method to to_thread, it works.

    with (
        patch("httpx.AsyncClient", side_effect=mock_client_cls),
        patch("pathlib.Path.mkdir"),
        patch("builtins.open", new_callable=MagicMock) as mock_open,
    ):
        mock_file = MagicMock()
        mock_open.return_value = mock_file
        mock_open.return_value.__enter__.return_value = mock_file

        # Run download
        result_json = await download_media(
            ["http://example.com/file.jpg"], "/tmp/downloads"
        )

        # Verify client.stream was called instead of client.get
        # The code creates a client instance, then calls client.stream
        mock_client_instance.stream.assert_called_once()
        args, kwargs = mock_client_instance.stream.call_args
        assert args[0] == "GET"
        assert args[1] == "http://example.com/file.jpg"
        assert kwargs.get("follow_redirects") is True

        # Verify client.get was NOT called
        mock_client_instance.get.assert_not_called()

        # Verify writes
        # We expect 2 chunks
        assert mock_file.write.call_count == 2
        mock_file.write.assert_any_call(b"chunk1")
        mock_file.write.assert_any_call(b"chunk2")

        # Verify result content
        results = json.loads(result_json)
        assert len(results) == 1
        assert results[0]["size"] == 12  # len("chunk1") + len("chunk2")
