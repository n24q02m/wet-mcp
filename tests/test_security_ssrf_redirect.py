from unittest.mock import AsyncMock, patch
from urllib.parse import urlparse

import httpx
import pytest

from wet_mcp.sources.crawler import download_media


@pytest.mark.asyncio
async def test_ssrf_redirect_fix(tmp_path):
    safe_url = "http://safe.com/image.png"
    unsafe_url = "http://127.0.0.1:8000/secret.txt"
    output_dir = tmp_path / "downloads"
    output_dir.mkdir()

    with patch("wet_mcp.sources.crawler.is_safe_url") as mock_is_safe:
        def side_effect(url):
            # Parse the URL to safely check the domain/IP
            parsed = urlparse(str(url))
            if parsed.hostname == "safe.com":
                return True
            if parsed.hostname == "127.0.0.1":
                return False
            return True
        mock_is_safe.side_effect = side_effect

        with patch("httpx.AsyncClient") as MockClient:
            client_instance = AsyncMock()
            MockClient.return_value.__aenter__.return_value = client_instance

            # Setup responses
            req1 = httpx.Request("GET", safe_url)
            r1 = httpx.Response(302, headers={"Location": unsafe_url}, request=req1)

            req2 = httpx.Request("GET", unsafe_url)
            r2 = httpx.Response(200, content=b"SECRET", request=req2)

            client_instance.get.side_effect = [r1, r2]

            try:
                # Execute
                await download_media([safe_url], str(output_dir))
            except Exception:
                pass  # Ignore runtime errors if mocked incorrectly, we care about calls

            # Verification:

            # 1. Check calls to client.get
            if client_instance.get.call_count == 0:
                pytest.fail("client.get was not called")

            # 2. Check that follow_redirects=False was used in the first call
            # Current vulnerable code uses True.
            _, kwargs = client_instance.get.call_args_list[0]
            if kwargs.get("follow_redirects") is True:
                pytest.fail("VULNERABLE: follow_redirects=True used")

            # 3. Check is_safe_url calls
            mock_is_safe.assert_any_call(safe_url)

            # It should be called for unsafe_url (the redirect target)
            try:
                mock_is_safe.assert_any_call(unsafe_url)
            except AssertionError:
                pytest.fail("VULNERABLE: Redirect target was NOT checked by is_safe_url")

            # 4. client.get should NOT be called for unsafe_url
            if client_instance.get.call_count > 1:
                # Check 2nd call
                args2, _ = client_instance.get.call_args_list[1]
                if str(args2[0]) == unsafe_url:
                    pytest.fail("VULNERABLE: Unsafe URL was fetched")
