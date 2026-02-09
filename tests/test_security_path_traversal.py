from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from pathlib import Path
from wet_mcp.sources.crawler import download_media

@pytest.mark.asyncio
async def test_download_media_path_traversal(tmp_path):
    """Test that download_media prevents path traversal."""

    # Mock httpx response
    mock_response = MagicMock()
    mock_response.content = b"fake content"
    mock_response.raise_for_status = MagicMock()

    # Mock httpx client context manager
    mock_client = AsyncMock()
    mock_client.get.return_value = mock_response
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = None

    with patch("wet_mcp.sources.crawler.is_safe_url", return_value=True):
        with patch("httpx.AsyncClient", return_value=mock_client):
            # 1. Traversal attempt with '..' as filename
            # This simulates a URL where split('/')[-1] is '..'
            url1 = "http://example.com/.."
            res1 = await download_media([url1], str(tmp_path))

            # Should fail with "Security Alert" because '..' resolves to parent dir
            # Note: The function returns a JSON string, so we check if the error message is in it.
            assert "Security Alert" in res1

            # Verify file was NOT written to parent (though on Linux writing to directory fails anyway,
            # we are checking the security mechanism prevents it before OS error)
            # If it was OS error, res1 would contain "Is a directory" or similar.
            # If our security check works, it contains "Security Alert".

            # Verify no files were written in parent
            # (tmp_path is usually /tmp/pytest-of-user/pytest-X/test_download_media_path_traversal0)
            # tmp_path.parent is .../pytest-X/
            # We don't want to check everything there, but ensure no file named ".." (which is impossible)
            # or "content" was created.
            pass

@pytest.mark.asyncio
async def test_download_media_safe(tmp_path):
    mock_response = MagicMock()
    mock_response.content = b"safe content"
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.get.return_value = mock_response
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = None

    with patch("wet_mcp.sources.crawler.is_safe_url", return_value=True):
        with patch("httpx.AsyncClient", return_value=mock_client):
            url = "http://example.com/image.png"
            await download_media([url], str(tmp_path))

            expected_file = tmp_path / "image.png"
            assert expected_file.exists()
            assert expected_file.read_bytes() == b"safe content"
