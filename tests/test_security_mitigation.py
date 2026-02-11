
import asyncio
import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch, AsyncMock

import pytest
from wet_mcp.sources.crawler import download_media

@pytest.mark.asyncio
async def test_download_media_ssrf_mitigation(tmp_path):
    """
    Verifies that download_media blocks unsafe URLs (SSRF).
    """
    unsafe_url = "http://127.0.0.1:8080/sensitive_data"

    mock_response = MagicMock()
    mock_response.content = b"secret data"
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.get.return_value = mock_response
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = None

    with patch("httpx.AsyncClient", return_value=mock_client):
        result_json = await download_media([unsafe_url], str(tmp_path))

        results = json.loads(result_json)
        result = results[0]

        # Verify request was NOT made
        assert not mock_client.get.called, "SSRF Mitigation Failed: Request was made to unsafe URL!"

        # Verify error message
        assert "Security Alert" in result.get("error", ""), f"Unexpected result: {result}"

@pytest.mark.asyncio
async def test_download_media_path_traversal_mitigation(tmp_path):
    """
    Verifies path traversal mitigation in download_media.
    """
    # URL that produces '..' as filename via split if not sanitized
    unsafe_url = "http://example.com/.."

    mock_response = MagicMock()
    mock_response.content = b"pwned"
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.get.return_value = mock_response
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = None

    # Patch is_safe_url to allow the URL so we reach file writing part
    # We want to test path traversal logic, not SSRF logic here.
    with patch("wet_mcp.sources.crawler.is_safe_url", return_value=True):
        with patch("httpx.AsyncClient", return_value=mock_client):
            # Create a subdirectory to act as download dir
            download_dir = tmp_path / "downloads"
            download_dir.mkdir()

            # Run download
            result_json = await download_media([unsafe_url], str(download_dir))
            results = json.loads(result_json)
            result = results[0]

            # The download should fail due to path traversal check
            assert "error" in result
            assert "Security Alert" in result["error"], f"Expected Security Alert, got: {result['error']}"

            # Verify nothing was written to parent of download_dir
            # (If it wrote to .., it would be in tmp_path)
            # Since filename is '..', if written, it would be 'download_dir/..' = 'tmp_path'.
            # 'tmp_path' is a directory, so write_bytes would fail with IsADirectoryError if it tried.
            # But the check should catch it before write_bytes.

            # To be sure check call to write_bytes wasn't made?
            # But we are using real write_bytes in current code (via asyncio.to_thread).
            pass

@pytest.mark.asyncio
async def test_analyze_media_path_traversal_mitigation():
    """
    Verifies that analyze_media blocks access to files outside allowed directories.
    """
    from wet_mcp.llm import analyze_media
    from wet_mcp.config import settings

    # Setup settings to have a specific download dir
    # We need to patch settings.download_dir
    # Since settings is instantiated in config.py, we patch the instance.

    with patch.object(settings, "download_dir", "/tmp/wet-mcp-safe"):
        with patch.object(settings, "api_keys", "dummy"): # Satisfy api_keys check
            # Attempt to access /etc/passwd
            result = await analyze_media("/etc/passwd")

            assert "Security Alert" in result
            assert "Access denied" in result
