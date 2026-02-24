import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from wet_mcp.sources.crawler import download_media


@pytest.mark.asyncio
async def test_download_media_ssrf_protection():
    """Test that download_media blocks unsafe URLs (SSRF protection)."""
    mock_client = AsyncMock()
    mock_response = MagicMock()
    mock_response.content = b"secret data"
    mock_response.raise_for_status = MagicMock()
    mock_client.get.return_value = mock_response

    mock_client_cls = MagicMock()
    mock_client_cls.return_value.__aenter__.return_value = mock_client
    mock_client_cls.return_value.__aexit__.return_value = None

    with patch("httpx.AsyncClient", mock_client_cls):
        url = "http://localhost/secret.txt"
        with patch("pathlib.Path.mkdir"), patch("pathlib.Path.write_bytes"):
            result_json = await download_media([url], "/tmp/downloads")

        # The request was NOT made because it's unsafe
        # Note: In the new implementation, we use client.build_request and client.send
        # client.get is not used.
        mock_client.get.assert_not_called()
        mock_client.send.assert_not_called()

        results = json.loads(result_json)
        assert len(results) == 1
        assert results[0]["url"] == url
        assert "error" in results[0]
        # Updated assertion to match specific error message from resolve_safe_url
        assert "Security Alert: Blocked localhost: localhost" in results[0]["error"]
