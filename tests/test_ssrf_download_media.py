import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from wet_mcp.sources.crawler import download_media


@pytest.mark.asyncio
async def test_download_media_ssrf_protection():
    """Test that download_media blocks unsafe URLs (SSRF protection)."""
    mock_client = AsyncMock()
    # Mock stream method
    mock_client.stream = MagicMock()

    # Mock stream context manager
    mock_response = AsyncMock()
    mock_response.raise_for_status = MagicMock()

    mock_stream_ctx = MagicMock()
    mock_stream_ctx.__aenter__.return_value = mock_response
    mock_stream_ctx.__aexit__.return_value = None
    mock_client.stream.return_value = mock_stream_ctx

    # Mock client constructor
    mock_client_cls = MagicMock()
    mock_client_cls.return_value.__aenter__.return_value = mock_client
    mock_client_cls.return_value.__aexit__.return_value = None

    with patch("httpx.AsyncClient", mock_client_cls):
        url = "http://localhost/secret.txt"

        # Patch open to prevent actual file I/O
        with patch("pathlib.Path.mkdir"), patch("builtins.open"):
            result_json = await download_media([url], "/tmp/downloads")

        # The request was NOT made because it's unsafe
        mock_client.stream.assert_not_called()
        mock_client.get.assert_not_called()

        results = json.loads(result_json)
        assert len(results) == 1
        assert results[0]["url"] == url
        assert "error" in results[0]
        assert "Security Alert: Unsafe URL blocked" in results[0]["error"]
