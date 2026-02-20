import json
from unittest.mock import AsyncMock, MagicMock, patch, call
import pytest
from wet_mcp.sources.crawler import download_media

@pytest.mark.asyncio
async def test_download_media_ssrf_redirect_protection():
    """
    Test that download_media manually follows redirects and blocks unsafe URLs.
    """
    initial_url = "http://safe.com/redirect"
    unsafe_url = "http://localhost/secret.txt"

    # Mock responses
    # First response: 302 Redirect to unsafe_url
    response1 = MagicMock()
    response1.status_code = 302
    response1.is_redirect = True
    response1.headers = {"location": unsafe_url}
    response1.raise_for_status = MagicMock()

    # Second response: Should NOT be fetched if protection works
    response2 = MagicMock()
    response2.status_code = 200
    response2.is_redirect = False
    response2.content = b"secret data"
    response2.raise_for_status = MagicMock()
    # Important: set the url property of the response to be a string or object that mocks it
    # But here we don't expect it to be reached.
    response2.url = unsafe_url

    mock_client = AsyncMock()
    # If we call get with initial_url, return response1
    # If we call get with unsafe_url, return response2 (should not happen)

    async def side_effect(url, follow_redirects=False):
        if url == initial_url:
            return response1
        if url == unsafe_url:
            return response2
        return MagicMock()

    mock_client.get.side_effect = side_effect

    mock_client_cls = MagicMock()
    mock_client_cls.return_value.__aenter__.return_value = mock_client
    mock_client_cls.return_value.__aexit__.return_value = None

    # We need to control is_safe_url.
    # It should return True for initial_url, and False for unsafe_url.

    def mock_is_safe_url(url):
        if url == initial_url:
            return True
        if url == unsafe_url:
            return False
        return True # Default safe

    with patch("httpx.AsyncClient", mock_client_cls):
        with patch("wet_mcp.sources.crawler.is_safe_url", side_effect=mock_is_safe_url):
            with patch("pathlib.Path.mkdir"), patch("pathlib.Path.write_bytes"):
                result_json = await download_media([initial_url], "/tmp/downloads")

    # Verify results
    results = json.loads(result_json)
    assert len(results) == 1
    assert results[0]["url"] == initial_url
    assert "error" in results[0]
    assert "Security Alert: Unsafe URL blocked" in results[0]["error"]

    # Verify calls
    # Should call get with initial_url and follow_redirects=False
    mock_client.get.assert_any_call(initial_url, follow_redirects=False)

    # Should NOT call get with unsafe_url
    # Because is_safe_url(unsafe_url) returned False before the call
    assert call(unsafe_url, follow_redirects=False) not in mock_client.get.call_args_list
