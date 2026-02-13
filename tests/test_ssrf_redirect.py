import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

@pytest.mark.asyncio
async def test_download_media_ssrf_redirect():
    """Test that download_media blocks unsafe redirects (SSRF protection)."""

    # Mock redirect response
    redirect_response = MagicMock()
    redirect_response.status_code = 302
    redirect_response.headers = {"location": "http://localhost/secret.txt"}
    redirect_response.is_redirect = True
    redirect_response.raise_for_status = MagicMock()
    # Ensure content is empty to simulate a redirect response body
    redirect_response.content = b""

    # Mock final response (should NOT be reached if secure)
    final_response = MagicMock()
    final_response.status_code = 200
    final_response.content = b"secret data"
    final_response.is_redirect = False
    final_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    # The client.get call will be made twice if redirect is followed manually:
    # 1. First call returns 302
    # 2. Second call returns 200 (if not blocked)
    mock_client.get.side_effect = [redirect_response, final_response]

    mock_client_cls = MagicMock()
    mock_client_cls.return_value.__aenter__.return_value = mock_client
    mock_client_cls.return_value.__aexit__.return_value = None

    with patch("httpx.AsyncClient", mock_client_cls):
        # Patch is_safe_url to allow initial URL but block localhost
        with patch("wet_mcp.sources.crawler.is_safe_url") as mock_is_safe:
            # Allow http://safe.com, block http://localhost...
            def side_effect(url):
                if "localhost" in url:
                    return False
                return True
            mock_is_safe.side_effect = side_effect

            from wet_mcp.sources.crawler import download_media

            with patch("pathlib.Path.mkdir"), patch("pathlib.Path.write_bytes"):
                # Initial URL is safe
                result_json = await download_media(["http://safe.com/image.png"], "/tmp/downloads")

            results = json.loads(result_json)

            # Expect error due to unsafe redirect
            if "error" not in results[0]:
                 # If vulnerable, it returns success with redirect content or final content depending on how mocked.
                 pytest.fail(f"Vulnerability: Did not block unsafe redirect. Result: {results[0]}")

            assert "Security Alert" in results[0]["error"]
            assert "Unsafe URL blocked" in results[0]["error"]

            # Verify calls
            # is_safe_url should be called for initial URL AND redirected URL
            assert mock_is_safe.call_count >= 2
            mock_is_safe.assert_any_call("http://localhost/secret.txt")
