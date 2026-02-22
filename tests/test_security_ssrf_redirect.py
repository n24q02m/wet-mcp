import json
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
import httpx
from wet_mcp.sources.crawler import download_media

@pytest.mark.asyncio
async def test_download_media_ssrf_redirect_protection():
    """Test that download_media manually handles redirects and checks is_safe_url."""

    # Mock behavior:
    # 1. Initial request to safe URL -> 302 to unsafe URL
    # 2. Code should check unsafe URL and BLOCK it
    # 3. Code should NOT make a request to the unsafe URL

    safe_url = "http://example.com/safe"
    unsafe_redirect = "http://localhost/secret"

    mock_client = AsyncMock()

    # We want to verify that follow_redirects is FALSE
    # And that the code handles the redirect manually.

    # Define responses
    response1 = MagicMock()
    response1.status_code = 302
    response1.is_redirect = True
    response1.headers = {"location": unsafe_redirect}
    # Response.url must be the requested URL for relative redirect resolution
    response1.url = httpx.URL(safe_url)
    response1.history = [] # No history yet

    # If the code follows the redirect, it would call client.get(unsafe_redirect)
    # We want to ensure it DOES NOT do that, or if it does, it catches it before request?
    # Actually, is_safe_url check should prevent the second request.

    mock_client.get.return_value = response1

    mock_client_cls = MagicMock()
    mock_client_cls.return_value.__aenter__.return_value = mock_client
    mock_client_cls.return_value.__aexit__.return_value = None

    with patch("httpx.AsyncClient", mock_client_cls):
        with patch("pathlib.Path.mkdir"), patch("pathlib.Path.write_bytes"):
             # We expect an error in the result because the redirect is unsafe
            result_json = await download_media([safe_url], "/tmp/downloads")

    results = json.loads(result_json)
    assert len(results) == 1
    assert results[0]["url"] == safe_url

    # Verify follow_redirects=True was NOT used (this is the key fix)
    # The current code USES follow_redirects=True, so this assertion would fail if we could inspect it.
    # But since we mock return_value, the current code will just return the 302 response and write it.
    # It won't report an error.

    # So if the current code is vulnerable, it returns success (writing the 302 content).
    # The fixed code should return an error.

    assert "error" in results[0], "Should report error for unsafe redirect"
    assert "Security Alert" in results[0]["error"] or "Unsafe URL" in results[0]["error"]
