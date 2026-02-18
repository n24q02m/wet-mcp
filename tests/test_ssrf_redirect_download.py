import json
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

from wet_mcp.sources.crawler import download_media


@pytest.mark.asyncio
async def test_download_media_handles_redirects_securely():
    """
    Test that download_media manually handles redirects and blocks unsafe ones.
    """
    mock_client = AsyncMock()

    # We simulate a redirect chain:
    # 1. http://example.com/image.jpg -> 302 -> http://localhost/secret

    # Response 1: 302 Redirect
    response1 = MagicMock()
    response1.status_code = 302
    response1.is_redirect = True
    response1.headers = {"Location": "http://localhost/secret"}
    response1.url = "http://example.com/image.jpg"

    # Response 2: Should NOT be reached if we block localhost

    # Configure client.get side_effect
    mock_client.get.return_value = response1

    mock_client_cls = MagicMock()
    mock_client_cls.return_value.__aenter__.return_value = mock_client
    mock_client_cls.return_value.__aexit__.return_value = None

    with patch("httpx.AsyncClient", mock_client_cls):
        url = "http://example.com/image.jpg"

        # We Mock is_safe_url to allow example.com but BLOCK localhost
        with patch("wet_mcp.sources.crawler.is_safe_url") as mock_is_safe:

            def side_effect(u):
                # Use exact match to avoid CodeQL "arbitrary position" warnings
                if u == "http://example.com/image.jpg":
                    return True
                if u == "http://localhost/secret":
                    return False
                return True

            mock_is_safe.side_effect = side_effect

            with patch("pathlib.Path.mkdir"), patch("pathlib.Path.write_bytes"):
                result = await download_media([url], "/tmp/downloads")

    # Verify calls
    # 1. client.get called with follow_redirects=False for initial URL
    mock_client.get.assert_called_with(url, follow_redirects=False)

    # 2. client.get should NOT be called for the second URL (localhost) because is_safe_url blocks it
    # But wait, did the loop continue?
    # Loop:
    #   get(url) -> response1 (redirect)
    #   check location -> http://localhost/secret
    #   check is_safe_url -> False
    #   return error
    # So client.get is called ONCE.
    assert mock_client.get.call_count == 1

    # 3. Check result contains error
    data = json.loads(result)
    assert len(data) == 1
    assert "error" in data[0]
    assert "Security Alert" in data[0]["error"]
    assert "redirect" in data[0]["error"]


@pytest.mark.asyncio
async def test_download_media_follows_safe_redirects():
    """
    Test that download_media follows safe redirects.
    """
    mock_client = AsyncMock()

    # 1. http://example.com/image.jpg -> 302 -> http://example.com/real_image.jpg
    # 2. http://example.com/real_image.jpg -> 200 OK

    response1 = MagicMock()
    response1.status_code = 302
    response1.is_redirect = True
    response1.headers = {"Location": "http://example.com/real_image.jpg"}
    response1.url = "http://example.com/image.jpg"

    response2 = MagicMock()
    response2.status_code = 200
    response2.is_redirect = False
    response2.url = "http://example.com/real_image.jpg"
    response2.content = b"image data"
    response2.raise_for_status = MagicMock()

    mock_client.get.side_effect = [response1, response2]

    mock_client_cls = MagicMock()
    mock_client_cls.return_value.__aenter__.return_value = mock_client
    mock_client_cls.return_value.__aexit__.return_value = None

    with patch("httpx.AsyncClient", mock_client_cls):
        url = "http://example.com/image.jpg"

        with patch("wet_mcp.sources.crawler.is_safe_url", return_value=True):
            with patch("pathlib.Path.mkdir"), patch("pathlib.Path.write_bytes"):
                result = await download_media([url], "/tmp/downloads")

    # Verify calls
    assert mock_client.get.call_count == 2
    mock_client.get.assert_has_calls(
        [
            call(url, follow_redirects=False),
            call("http://example.com/real_image.jpg", follow_redirects=False),
        ]
    )

    data = json.loads(result)
    assert len(data) == 1
    assert "path" in data[0]
    assert "error" not in data[0]
