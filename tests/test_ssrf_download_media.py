import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from wet_mcp.sources.crawler import download_media


@pytest.mark.asyncio
async def test_download_media_ssrf_protection():
    # Setup mock client
    mock_client = AsyncMock()
    mock_response = MagicMock()
    mock_response.content = b"secret data"
    mock_response.raise_for_status = MagicMock()
    mock_client.get.return_value = mock_response

    # Mock AsyncClient context manager
    mock_client_cls = MagicMock()
    mock_client_cls.return_value.__aenter__.return_value = mock_client
    mock_client_cls.return_value.__aexit__.return_value = None

    with patch("httpx.AsyncClient", mock_client_cls):
        # Act: Try to download from localhost
        url = "http://localhost/secret.txt"
        with patch("pathlib.Path.mkdir"), patch("pathlib.Path.write_bytes"):
             result_json = await download_media([url], "/tmp/downloads")

        # Assert: The request was NOT made because it's unsafe
        mock_client.get.assert_not_called()

        results = json.loads(result_json)
        assert len(results) == 1
        assert results[0]["url"] == url
        assert "error" in results[0]
        assert "Security Alert: Unsafe URL blocked" in results[0]["error"]

if __name__ == "__main__":
    # If run directly
    import asyncio
    asyncio.run(test_download_media_ssrf_protection())
