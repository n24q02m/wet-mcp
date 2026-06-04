import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from wet_mcp.sources.crawler import download_media


@pytest.mark.asyncio
async def test_download_media_unsafe_redirect(tmp_path):
    """Test unsafe URL detection during redirects."""
    url = "http://example.com/start"
    unsafe_url = "http://169.254.169.254/latest/meta-data/"

    mock_response_1 = MagicMock()
    mock_response_1.is_redirect = True
    mock_response_1.headers = {"Location": unsafe_url}

    mock_client = AsyncMock()
    mock_client.get.side_effect = [mock_response_1]

    mock_client_instance = AsyncMock()
    mock_client_instance.__aenter__.return_value = mock_client
    mock_client_instance.__aexit__.return_value = None

    mock_client_cls = MagicMock(return_value=mock_client_instance)

    with patch("wet_mcp.sources.crawler._safe_httpx_client", mock_client_cls):
        with patch("wet_mcp.sources.crawler.is_safe_url", side_effect=[True, False]):
            result_json = await download_media([url], str(tmp_path))

    results = json.loads(result_json)
    assert len(results) == 1
    assert "Security Alert" in results[0]["error"]
    assert results[0]["url"] == url


@pytest.mark.asyncio
async def test_download_media_max_redirects(tmp_path):
    """Test max redirects exceeded."""
    url = "http://example.com/1"

    def redirect_side_effect(target_url, **kwargs):
        import re

        match = re.search(r"/(\d+)$", target_url)
        current_num = int(match.group(1)) if match else 1
        next_num = current_num + 1
        resp = MagicMock()
        resp.is_redirect = True
        resp.headers = {"Location": f"http://example.com/{next_num}"}
        resp.content = b"redirect body"
        resp.raise_for_status = MagicMock()
        return resp

    mock_client = AsyncMock()
    mock_client.get.side_effect = redirect_side_effect

    mock_client_instance = AsyncMock()
    mock_client_instance.__aenter__.return_value = mock_client
    mock_client_instance.__aexit__.return_value = None

    mock_client_cls = MagicMock(return_value=mock_client_instance)

    with patch("wet_mcp.sources.crawler._safe_httpx_client", mock_client_cls):
        with patch("wet_mcp.sources.crawler.is_safe_url", return_value=True):
            result_json = await download_media([url], str(tmp_path))

    results = json.loads(result_json)
    assert len(results) == 1
    assert results[0]["url"] == url
    assert "path" in results[0]


@pytest.mark.asyncio
async def test_download_media_path_traversal_check(tmp_path):
    """Test the explicit path traversal check."""

    mock_response = MagicMock()
    mock_response.is_redirect = False
    mock_response.content = b"test"
    mock_response.headers = {}
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.get.return_value = mock_response

    mock_client_instance = AsyncMock()
    mock_client_instance.__aenter__.return_value = mock_client
    mock_client_instance.__aexit__.return_value = None

    mock_client_cls = MagicMock(return_value=mock_client_instance)

    with patch("wet_mcp.sources.crawler._safe_httpx_client", mock_client_cls):
        with patch("wet_mcp.sources.crawler.is_safe_url", return_value=True):
            original_resolve = Path.resolve

            def mock_resolve(self):
                if self.name == "malicious.txt":
                    return Path("/tmp/outside/malicious.txt")
                return original_resolve(self)

            with patch("pathlib.Path.resolve", side_effect=mock_resolve, autospec=True):
                result_json = await download_media(
                    ["http://example.com/malicious.txt"], str(tmp_path)
                )

    results = json.loads(result_json)
    assert len(results) == 1
    assert "Security Alert: Path traversal attempt detected" in results[0]["error"]


@pytest.mark.asyncio
async def test_download_media_extension_inference(tmp_path):
    """Test filename extension inference from Content-Type."""
    url = "http://example.com/image_without_ext"

    mock_response = MagicMock()
    mock_response.is_redirect = False
    mock_response.content = b"fake image"
    # Use real httpx Headers for better compatibility
    mock_response.headers = httpx.Headers({"Content-Type": "image/jpeg"})
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.get.return_value = mock_response

    mock_client_instance = AsyncMock()
    mock_client_instance.__aenter__.return_value = mock_client
    mock_client_instance.__aexit__.return_value = None

    mock_client_cls = MagicMock(return_value=mock_client_instance)

    with patch("wet_mcp.sources.crawler._safe_httpx_client", mock_client_cls):
        with patch("wet_mcp.sources.crawler.is_safe_url", return_value=True):
            result_json = await download_media([url], str(tmp_path))

    results = json.loads(result_json)
    assert "path" in results[0]
    path = results[0]["path"]
    assert path.lower().endswith(".jpg") or path.lower().endswith(".jpeg")
