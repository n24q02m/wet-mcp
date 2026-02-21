import json
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from wet_mcp.sources.crawler import download_media

@pytest.mark.asyncio
async def test_download_media_ssrf_redirect_protection():
    """
    Test that download_media protects against SSRF via redirect.

    The initial URL is safe, but it redirects to an unsafe URL (localhost).
    The code must detect this and block the download.
    """

    # Setup mocks
    mock_client = AsyncMock()

    # We simulate what httpx does when follow_redirects=True (current behavior)
    # OR what we want to prevent.
    # Actually, to test the FIX, we will need to verify that we are MANUALLY handling redirects.
    # But for now, let's just assert that the outcome is safe.

    # If the code uses follow_redirects=True, httpx returns the final response.
    # If the code changes to manual handling, it will see the 301/302.

    # Let's mock the scenario where the code asks for the URL.
    # The vulnerability is that if we trust httpx to follow redirects, it returns the final content.

    # To properly test the fix (which will likely involve a loop), we need to mock
    # the client to return a redirect response first, then the final response.

    # Mock response 1: 301 Redirect to localhost
    response1 = MagicMock()
    response1.status_code = 301
    response1.headers = {"location": "http://localhost/secret"}
    response1.url = "http://safe.com/redirect"
    response1.is_redirect = True
    # If follow_redirects=False (our fix), this is what we get.

    # Mock response 2: 200 OK from localhost (if we were to follow it)
    response2 = MagicMock()
    response2.status_code = 200
    response2.content = b"secret data"
    response2.url = "http://localhost/secret"
    response2.is_redirect = False

    # We need to configure the mock client to return these in sequence IF called.
    # If the code uses follow_redirects=True, httpx (the real library) handles the sequence.
    # But since we are mocking AsyncClient, we have to simulate the behavior depending on
    # how the code calls it.

    # Scenario A: Code uses follow_redirects=True (VULNERABLE)
    # In this case, httpx "magically" returns response2.
    # But we can't easily mock the "magic" inside a mock object unless we implement side_effect.

    # Scenario B: Code uses follow_redirects=False (SECURE FIX)
    # In this case, the code gets response1. Then it checks the location.
    # It sees localhost, and SHOULD stop.

    # So, let's setup the mock to return response1 first.
    # If the code is fixed, it will inspect response1, see the unsafe location, and STOP.
    # It will NOT call client.get again for the unsafe URL.

    # If the code is NOT fixed (still uses follow_redirects=True), the mock needs to behave like httpx.
    # But wait, if we mock client.get, we control what it returns.
    # If the code calls `client.get(..., follow_redirects=True)`, we can make the mock return response2 immediately
    # to simulate the vulnerability.

    async def side_effect_get(url, **kwargs):
        # Check if the code is asking to follow redirects
        follow_redirects = kwargs.get("follow_redirects", False)

        if url == "http://safe.com/redirect":
            if follow_redirects:
                # Simulate httpx following the redirect automatically to the unsafe destination
                # The vulnerability is that the code accepts this result.
                return response2
            else:
                # Return the redirect response for manual handling
                return response1
        elif url == "http://localhost/secret":
             # If the code manually tries to fetch the unsafe URL (which it shouldn't), return it
             return response2
        return MagicMock()

    mock_client.get.side_effect = side_effect_get

    mock_client_cls = MagicMock()
    mock_client_cls.return_value.__aenter__.return_value = mock_client
    mock_client_cls.return_value.__aexit__.return_value = None

    # Patch is_safe_url
    def side_effect_is_safe_url(url):
        # http://safe.com/redirect is SAFE
        # http://localhost/secret is UNSAFE
        if "localhost" in str(url) or "127.0.0.1" in str(url):
            return False
        return True

    with patch("wet_mcp.sources.crawler.is_safe_url", side_effect=side_effect_is_safe_url):
        with patch("httpx.AsyncClient", mock_client_cls):
            url = "http://safe.com/redirect"

            with patch("pathlib.Path.mkdir"), patch("pathlib.Path.write_bytes"):
                result_json = await download_media([url], "/tmp/downloads")

    results = json.loads(result_json)

    # If the code is secure, it should have errored out.
    assert len(results) == 1
    assert "error" in results[0], f"Vulnerability: Download succeeded for {results[0]['url']}"
    # The error message should indicate an unsafe redirect
    assert "Security Alert: Unsafe redirect" in results[0]["error"]
