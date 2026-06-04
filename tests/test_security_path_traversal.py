import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from wet_mcp.sources.crawler import download_media


@pytest.mark.asyncio
async def test_download_media_path_traversal(tmp_path):
    """Test that download_media prevents path traversal."""

    # Mock httpx response
    mock_response = MagicMock()
    mock_response.content = b"fake content"
    mock_response.raise_for_status = MagicMock()
    mock_response.is_redirect = False
    mock_response.headers = {"content-type": "image/png"}

    # Mock httpx client context manager
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
            res1_raw = await download_media([url1], str(tmp_path))
            res1 = json.loads(res1_raw)
            assert any("Security Alert" in r.get("error", "") for r in res1)

            # 2. Traversal attempt with URL-encoded '..'
            url2 = "http://example.com/%2e%2e"
            res2_raw = await download_media([url2], str(tmp_path))
            res2 = json.loads(res2_raw)
            assert any("Security Alert" in r.get("error", "") for r in res2)

            # 3. Attempt with encoded multiple traversals and absolute path
            # This should be neutralized by .name and confirmed by is_relative_to
            url3 = "http://example.com/%2e%2e%2f%2e%2e%2fetc%2fpasswd"
            res3_raw = await download_media([url3], str(tmp_path))
            res3 = json.loads(res3_raw)
            p3 = Path(res3[0]["path"])
            assert p3.is_relative_to(tmp_path.resolve())
            assert p3.name == "passwd.png"

            # 4. Attempt with null byte - should be rejected or error
            url4 = "http://example.com/test.png%00.php"
            res4_raw = await download_media([url4], str(tmp_path))
            res4 = json.loads(res4_raw)
            assert "error" in res4[0]
            assert "null character" in res4[0]["error"].lower()

            # 5. Very long filename (DOS attempt)
            url5 = "http://example.com/" + ("a" * 300)
            res5_raw = await download_media([url5], str(tmp_path))
            res5 = json.loads(res5_raw)
            assert "error" in res5[0]
            assert "too long" in res5[0]["error"].lower()


@pytest.mark.asyncio
async def test_download_media_safe(tmp_path):
    mock_response = MagicMock()
    mock_response.content = b"safe content"
    mock_response.raise_for_status = MagicMock()
    mock_response.is_redirect = False
    mock_response.headers = {"content-type": "image/png"}

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
