import pytest
from unittest.mock import patch, AsyncMock, PropertyMock
import httpx
from wet_mcp.sources.crawler import download_media

@pytest.mark.asyncio
async def test_ssrf_redirect_fix(tmp_path):
    safe_url = "http://safe.com/image.png"
    unsafe_url = "http://127.0.0.1:8000/secret.txt"
    output_dir = tmp_path / "downloads"
    output_dir.mkdir()

    with patch("wet_mcp.sources.crawler.is_safe_url") as mock_is_safe:
        def side_effect(url):
            if "safe.com" in str(url): return True
            if "127.0.0.1" in str(url): return False
            return True
        mock_is_safe.side_effect = side_effect

        with patch("httpx.AsyncClient") as MockClient:
            client_instance = AsyncMock()
            MockClient.return_value.__aenter__.return_value = client_instance

            # Setup responses
            req1 = httpx.Request("GET", safe_url)
            r1 = httpx.Response(302, headers={"Location": unsafe_url}, request=req1)

            # We need to make sure response.url returns the correct URL
            # httpx.Response.url property returns self.request.url if not set explicitly via extension
            # But let's just patch it to be safe or rely on behavior.
            # Actually, let's just use what httpx gives us.

            req2 = httpx.Request("GET", unsafe_url)
            r2 = httpx.Response(200, content=b"SECRET", request=req2)

            client_instance.get.side_effect = [r1, r2]

            try:
                # Execute
                await download_media([safe_url], str(output_dir))
            except Exception as e:
                pass # Ignore runtime errors if mocked incorrectly, we care about calls

            # Verification:

            # 1. Check calls to client.get
            if client_instance.get.call_count == 0:
                pytest.fail("client.get was not called")

            # 2. Check that follow_redirects=False was used in the first call
            # Current vulnerable code uses True.
            args, kwargs = client_instance.get.call_args_list[0]
            if kwargs.get("follow_redirects") is True:
                 pytest.fail("VULNERABLE: follow_redirects=True used")

            # If we reach here, it means follow_redirects=False (or None/default, which is False for client instance usually, but client.get defaults to True? No, httpx.get defaults to True, client.get defaults to client setting).
            # Wait, client.get(url, follow_redirects=...) overrides client setting.

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
                args2, kwargs2 = client_instance.get.call_args_list[1]
                if str(args2[0]) == unsafe_url:
                     pytest.fail("VULNERABLE: Unsafe URL was fetched")
