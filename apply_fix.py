import sys
from pathlib import Path

# Fix the test file
test_path = Path("tests/test_security_path_traversal.py")
test_content = test_path.read_text()

# We need to make sure mock_response has is_redirect=False and headers={}
# The previous patch might have failed if indentation or context was slightly different or if it was already applied (idempotency).
# Let's write the whole file content to be sure.

new_test_content = """from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from wet_mcp.sources.crawler import download_media


@pytest.mark.asyncio
async def test_download_media_path_traversal(tmp_path):
    \"\"\"Test that download_media prevents path traversal.\"\"\"

    # Mock httpx response
    mock_response = MagicMock()
    mock_response.content = b"fake content"
    mock_response.raise_for_status = MagicMock()
    # Explicitly set is_redirect to False to avoid MagicMock returning a truthy mock object
    mock_response.is_redirect = False
    mock_response.headers = {}

    # Mock httpx client context manager
    mock_client = AsyncMock()
    # We need to mock build_request and send, not get, because the new implementation uses them
    mock_request = MagicMock()
    mock_client.build_request = MagicMock(return_value=mock_request)
    mock_client.send.return_value = mock_response

    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = None

    # We need to simulate is_safe_url passing for these URLs, or mock it.
    # Since we are testing path traversal, we assume the URL is "safe" network-wise but malicious filename-wise.
    # We also need to mock resolve_safe_url because the new implementation calls it.

    with patch("wet_mcp.sources.crawler.resolve_safe_url") as mock_resolve:
        # Return dummy values: ip_url, hostname, safe_ip
        # The ip_url should preserve the path/query so logic continues
        mock_resolve.side_effect = lambda url: (url, "example.com", "1.2.3.4")

        with patch("httpx.AsyncClient", return_value=mock_client):
            # 1. Traversal attempt with '..' as filename
            # This simulates a URL where split('/')[-1] is '..'
            url1 = "http://example.com/.."
            res1 = await download_media([url1], str(tmp_path))

            # Should fail with "Security Alert" because '..' resolves to parent dir
            assert "Security Alert" in res1


@pytest.mark.asyncio
async def test_download_media_safe(tmp_path):
    mock_response = MagicMock()
    mock_response.content = b"safe content"
    mock_response.raise_for_status = MagicMock()
    mock_response.is_redirect = False
    mock_response.headers = {}

    mock_client = AsyncMock()
    mock_request = MagicMock()
    mock_client.build_request = MagicMock(return_value=mock_request)
    mock_client.send.return_value = mock_response

    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = None

    with patch("wet_mcp.sources.crawler.resolve_safe_url") as mock_resolve:
        mock_resolve.side_effect = lambda url: (url, "example.com", "1.2.3.4")

        with patch("httpx.AsyncClient", return_value=mock_client):
            url = "http://example.com/image.png"
            await download_media([url], str(tmp_path))

            expected_file = tmp_path / "image.png"
            assert expected_file.exists()
            assert expected_file.read_bytes() == b"safe content"
"""

test_path.write_text(new_test_content)
print("Rewrote tests/test_security_path_traversal.py")
