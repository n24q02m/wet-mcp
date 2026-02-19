import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from wet_mcp.config import Settings
from wet_mcp.sources.crawler import download_media


@pytest.mark.asyncio
async def test_download_media_ssrf_protection(tmp_path):
    """Test that download_media blocks unsafe URLs (SSRF protection)."""
    mock_client = AsyncMock()
    mock_response = MagicMock()
    mock_response.content = b"secret data"
    mock_response.raise_for_status = MagicMock()
    mock_client.get.return_value = mock_response

    mock_client_cls = MagicMock()
    mock_client_cls.return_value.__aenter__.return_value = mock_client
    mock_client_cls.return_value.__aexit__.return_value = None

    # Patch settings to allow download to tmp_path
    test_settings = Settings(download_dir=str(tmp_path))

    with patch("wet_mcp.sources.crawler.settings", test_settings):
        with patch("httpx.AsyncClient", mock_client_cls):
            url = "http://localhost/secret.txt"

            # Use tmp_path as output_dir
            result_json = await download_media([url], str(tmp_path))

            # The request was NOT made because it's unsafe
            mock_client.get.assert_not_called()

            results = json.loads(result_json)
            assert len(results) == 1
            assert results[0]["url"] == url
            assert "error" in results[0]
            assert "Security Alert: Unsafe URL blocked" in results[0]["error"]
