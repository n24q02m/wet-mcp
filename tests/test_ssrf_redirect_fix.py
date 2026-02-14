import json
from unittest.mock import MagicMock, patch
from urllib.parse import urlparse

import httpx
import pytest

from wet_mcp.sources.crawler import download_media


@pytest.mark.asyncio
async def test_ssrf_redirect_protection():
    """
    Test that download_media manually handles redirects and blocks unsafe URLs (SSRF protection).
    """

    # Define a Mock Transport that simulates a redirect to localhost
    class MockTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request):
            url = str(request.url)
            parsed = urlparse(url)
            if parsed.hostname == "safe.com":
                return httpx.Response(
                    302, headers={"Location": "http://localhost/secret.txt"}
                )
            elif parsed.hostname == "localhost":
                return httpx.Response(200, content=b"SECRET_DATA_LEAKED")
            return httpx.Response(404)

    # Mock AsyncClient to use our transport
    # We must patch where AsyncClient is instantiated in download_media
    # download_media usage: async with httpx.AsyncClient(...) as client:

    mock_client_instance = httpx.AsyncClient(transport=MockTransport())

    mock_client_cls = MagicMock()
    mock_client_cls.return_value.__aenter__.return_value = mock_client_instance
    mock_client_cls.return_value.__aexit__.side_effect = mock_client_instance.__aexit__

    # Patch AsyncClient in the crawler module
    with patch("wet_mcp.sources.crawler.httpx.AsyncClient", mock_client_cls):
        # Also patch is_safe_url to ensure initial check passes
        with patch("wet_mcp.sources.crawler.is_safe_url") as mock_safe:
            # Allow safe.com, block localhost (simulating real behavior)
            def _mock_is_safe(u):
                try:
                    return urlparse(str(u)).hostname == "safe.com"
                except Exception:
                    return False

            mock_safe.side_effect = _mock_is_safe

            # Patch filesystem ops to avoid actual writes
            with patch("pathlib.Path.mkdir"), patch("pathlib.Path.write_bytes"):
                # Run download_media
                results_json = await download_media(
                    ["http://safe.com/image.png"], "/tmp"
                )

    results = json.loads(results_json)
    result = results[0]

    # The request should be blocked, so we expect an error
    if "error" not in result:
        pytest.fail(
            f"Security Check Failed: Downloaded data from {result.get('url', 'unknown')} instead of blocking unsafe redirect"
        )

    assert "Security Alert" in result["error"]
