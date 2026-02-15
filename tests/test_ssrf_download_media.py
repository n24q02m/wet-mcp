from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from wet_mcp.sources.crawler import download_media


@pytest.mark.asyncio
async def test_download_media_ssrf_redirect(tmp_path):
    # Setup mocks
    mock_is_safe_url = MagicMock()
    # Initial URL is safe
    mock_is_safe_url.side_effect = lambda url: "safe.com" in url

    # Mock httpx response to simulate a redirect if follow_redirects was False,
    # OR simulate the final response if follow_redirects was True.
    # The current code uses follow_redirects=True.

    # We want to verify that the code CHANGE handles redirects manually.
    # So we will mock httpx.AsyncClient.get to return a 302 first, then 200.

    with (
        patch("wet_mcp.sources.crawler.is_safe_url", mock_is_safe_url),
        patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get,
    ):
        # Scenario:
        # 1. Request to http://safe.com/image.png
        # 2. Redirects to http://unsafe.local/image.png
        # 3. Should be blocked.

        # If the code uses follow_redirects=True, mock_get is called ONCE with http://safe.com.
        # It would verify is_safe_url("http://safe.com") -> True.
        # Then it calls get().
        # To fail this test (demonstrate vulnerability), we can check if is_safe_url was called for the redirected URL.
        # But since we mock get(), we can't easily simulate the library's internal redirect logic triggering is_safe_url calls inside the library (it won't).

        # So we can't easily "fail" the test with the CURRENT code using mocks unless we assert on the implementation details.

        # Let's write the test assuming the DESIRED behavior (manual redirect handling).
        # If the current code runs, it will likely fail this test because it expects a single call with follow_redirects=True.

        target_url = "http://safe.com/image.png"
        redirect_url = "http://unsafe.local/image.png"

        # We need to configure the mock to behave like a real client if we were manually handling redirects.
        # First call returns 302. Second call (if it happens) returns 200.

        response1 = MagicMock(spec=httpx.Response)
        response1.status_code = 302
        response1.headers = {"Location": redirect_url}
        response1.url = httpx.URL(target_url)
        # is_redirect property is used by httpx, and likely by our manual logic
        response1.is_redirect = True
        response1.next_request = MagicMock()
        response1.next_request.url = redirect_url
        response1.content = b"fake content"

        # If the code follows the redirect, it would call get again.
        response2 = MagicMock(spec=httpx.Response)
        response2.status_code = 200
        response2.content = b"image data"
        response2.url = httpx.URL(redirect_url)
        response2.is_redirect = False

        mock_get.side_effect = [response1, response2]

        # Run the function
        # Note: We need to patch the semaphore or it might hang if not properly released/acquired in mocks?
        # The code uses a semaphore. We should be fine as long as we don't block.

        # Also, download_media writes to file.
        # We need to make sure output_dir is valid.

        results_json = await download_media([target_url], str(tmp_path))

        # If the code is VULNERABLE (current state):
        # It calls client.get(..., follow_redirects=True).
        # Our mock returns response1 (302).
        # The current code checks response.raise_for_status(). 302 doesn't raise exception usually?
        # Actually raise_for_status() does not raise for 3xx.
        # It proceeds to write response1.content (which is empty/mock) to file.
        # It does NOT check is_safe_url(redirect_url).

        # If the code is FIXED:
        # It calls client.get(..., follow_redirects=False).
        # It sees 302.
        # It checks is_safe_url(redirect_url) -> False.
        # It returns error.

        # So, assertions:
        # 1. is_safe_url should have been called with redirect_url (The unsafe one).
        # 2. The result should contain an error about "Security Alert" or "Unsafe URL".

        print(results_json)
        assert "unsafe.local" in str(mock_is_safe_url.call_args_list)
        assert "Security Alert" in results_json
