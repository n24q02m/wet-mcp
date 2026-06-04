from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from wet_mcp.sources.crawler import download_media


@pytest.mark.asyncio
async def test_download_media_path_traversal(tmp_path):
    """Test that download_media prevents path traversal."""
    mock_response = MagicMock()
    mock_response.content = b"fake content"
    mock_response.raise_for_status = MagicMock()
    mock_response.is_redirect = False

    mock_client = AsyncMock()
    mock_client.get.return_value = mock_response
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = None

    with patch("wet_mcp.sources.crawler.is_safe_url", return_value=True):
        with patch(
            "wet_mcp.sources.crawler.httpx.AsyncClient", return_value=mock_client
        ):
            # 1. Traversal attempt with '..' as filename
            url1 = "http://example.com/.."
            res1 = await download_media([url1], str(tmp_path))
            # Now it should be renamed to 'download' instead of failing with "Security Alert"
            # because the sanitization logic catches it before resolution.
            import json

            results1 = json.loads(res1)
            assert "path" in results1[0]
            assert results1[0]["path"].endswith("download")

            # 2. Encoded traversal sequence
            url2 = "http://example.com/%2e%2e%2fetc%2fpasswd"
            res2 = await download_media([url2], str(tmp_path))
            results2 = json.loads(res2)
            assert "path" in results2[0]
            # /etc/passwd -> should become 'passwd'
            assert results2[0]["path"].endswith("passwd")

            # 3. Encoded separator
            url3 = "http://example.com/foo%2fbar"
            res3 = await download_media([url3], str(tmp_path))
            results3 = json.loads(res3)
            assert "path" in results3[0]
            assert results3[0]["path"].endswith("bar")


@pytest.mark.asyncio
async def test_download_media_safe(tmp_path):
    mock_response = MagicMock()
    mock_response.content = b"safe content"
    mock_response.raise_for_status = MagicMock()
    mock_response.is_redirect = False

    mock_client = AsyncMock()
    mock_client.get.return_value = mock_response
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = None

    with patch("wet_mcp.sources.crawler.is_safe_url", return_value=True):
        with patch(
            "wet_mcp.sources.crawler.httpx.AsyncClient", return_value=mock_client
        ):
            url = "http://example.com/image.png"
            await download_media([url], str(tmp_path))

            expected_file = tmp_path / "image.png"
            assert expected_file.exists()
            assert expected_file.read_bytes() == b"safe content"
