from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from wet_mcp.sources.crawler import download_media


@pytest.mark.asyncio
async def test_download_media_streaming():
    # Setup mocks
    mock_client_instance = MagicMock()

    # Mock response
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()

    # Mock aiter_bytes async iterator
    async def async_iter():
        yield b"chunk1"
        yield b"chunk2"

    mock_response.aiter_bytes.return_value = async_iter()

    # Mock stream context manager
    mock_stream_ctx = MagicMock()
    mock_stream_ctx.__aenter__ = AsyncMock(return_value=mock_response)
    mock_stream_ctx.__aexit__ = AsyncMock(return_value=None)

    mock_client_instance.stream.return_value = mock_stream_ctx

    # Mock AsyncClient constructor
    mock_client_ctx = MagicMock()
    mock_client_ctx.__aenter__ = AsyncMock(return_value=mock_client_instance)
    mock_client_ctx.__aexit__ = AsyncMock(return_value=None)

    mock_client_cls = MagicMock(return_value=mock_client_ctx)

    # Mock file handling
    mock_file = MagicMock()
    mock_file_ctx = MagicMock()
    mock_file_ctx.__enter__.return_value = mock_file
    mock_file_ctx.__exit__.return_value = None
    mock_open = MagicMock(return_value=mock_file_ctx)

    url = "http://example.com/test.jpg"

    with (
        patch("httpx.AsyncClient", mock_client_cls),
        patch("builtins.open", mock_open),
        patch("wet_mcp.sources.crawler.is_safe_url", return_value=True),
        patch("pathlib.Path.mkdir"),
        patch("pathlib.Path.resolve", return_value=MagicMock()),
        patch("pathlib.Path.is_relative_to", return_value=True),
    ):
        await download_media([url], "/tmp")

    # Assert stream was called with correct args
    mock_client_instance.stream.assert_called_once()
    args, kwargs = mock_client_instance.stream.call_args
    assert args[0] == "GET"  # First arg to stream is method
    assert args[1] == url  # Second is URL
    assert kwargs.get("follow_redirects") is True

    # Assert file was written in chunks
    assert mock_file.write.call_count == 2
    mock_file.write.assert_any_call(b"chunk1")
    mock_file.write.assert_any_call(b"chunk2")
