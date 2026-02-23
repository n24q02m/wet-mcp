import json
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from wet_mcp.sources.crawler import download_media

@pytest.mark.asyncio
async def test_download_media_ssrf_redirect_protection():
    """Test that download_media blocks unsafe URLs in redirects."""

    # Mock response: Redirect to localhost
    mock_redirect = MagicMock()
    mock_redirect.status_code = 302
    mock_redirect.is_redirect = True
    mock_redirect.headers = {"Location": "http://localhost/secret.txt"}
    mock_redirect.url = "http://safe.com/image.png"
    mock_redirect.content = b"" # No content in redirect
    mock_redirect.raise_for_status = MagicMock()

    # Mock the client
    mock_client = AsyncMock()
    # We simulate that the first call returns a redirect.
    # The current vulnerable code (follow_redirects=True) would just get this and stop (since it's a mock).
    # The fixed code (manual handling) will see it's a redirect and inspect Location.
    mock_client.get.return_value = mock_redirect

    # Mock the context manager
    mock_client_cls = MagicMock()
    mock_client_cls.return_value.__aenter__.return_value = mock_client
    mock_client_cls.return_value.__aexit__.return_value = None

    with patch("httpx.AsyncClient", mock_client_cls):
        # We need to mock Path operations to avoid filesystem errors
        with patch("pathlib.Path.mkdir"), patch("pathlib.Path.write_bytes") as mock_write:
            url = "http://safe.com/image.png"
            result_json = await download_media([url], "/tmp/downloads")

            results = json.loads(result_json)
            result = results[0]

            # We expect the code to detect the unsafe redirect and return an error.
            # If it returns success (no error), it means it didn't check the redirect.
            if "error" not in result:
                pytest.fail("Vulnerability: The code did not block the unsafe redirect.")

            assert "Security Alert" in result["error"], f"Expected Security Alert, got: {result.get('error')}"
