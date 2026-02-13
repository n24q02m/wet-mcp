import json
import shutil
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from wet_mcp.config import settings
from wet_mcp.sources.crawler import download_media


@pytest.mark.asyncio
async def test_download_media_prevents_arbitrary_write():
    """Test that download_media prevents writing to arbitrary directories."""

    # Create temp dirs
    safe_dir = Path(tempfile.mkdtemp(prefix="wet_safe_"))
    sensitive_dir = Path(tempfile.mkdtemp(prefix="wet_sensitive_"))

    try:
        # We need to patch the attribute on the INSTANCE
        # verify wet_mcp.config.settings is the instance we are patching

        with patch.object(settings, "download_dir", str(safe_dir)):
            # Mock httpx response
            mock_response = MagicMock()
            mock_response.content = b"malicious content"
            mock_response.raise_for_status = MagicMock()

            # Mock client
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_response
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None

            with patch("wet_mcp.sources.crawler.is_safe_url", return_value=True):
                with patch("httpx.AsyncClient", return_value=mock_client):
                    target_url = "http://example.com/exploit.txt"

                    # 1. Attempt absolute path outside safe dir
                    # This should be blocked
                    print(f"Testing absolute path: {sensitive_dir}")
                    result_json = await download_media([target_url], str(sensitive_dir))
                    result = json.loads(result_json)

                    assert "error" in result
                    assert "Security Alert" in result["error"]

                    # Verify file was NOT created
                    assert not (sensitive_dir / "exploit.txt").exists()

                    # 2. Attempt relative path traversal (../sensitive)
                    # safe_dir and sensitive_dir are likely siblings in /tmp
                    # Let's try to go up and then down to sensitive
                    # e.g. safe_dir = /tmp/wet_safe_1
                    # sensitive_dir = /tmp/wet_sensitive_2
                    # relative = "../wet_sensitive_2"

                    relative_attack = f"../{sensitive_dir.name}"
                    print(f"Testing relative path: {relative_attack}")

                    result_json = await download_media([target_url], relative_attack)
                    result = json.loads(result_json)

                    assert "error" in result
                    assert "Security Alert" in result["error"]
                    # Verify file was NOT created
                    assert not (sensitive_dir / "exploit.txt").exists()

                    # 3. Attempt valid download (inside safe dir)
                    valid_subdir = "downloads"
                    print(f"Testing valid subdir: {valid_subdir}")
                    result_json = await download_media([target_url], valid_subdir)
                    results = json.loads(result_json)

                    assert isinstance(results, list)
                    assert results[0]["url"] == target_url

                    expected_path = safe_dir / valid_subdir / "exploit.txt"
                    assert expected_path.exists()

    finally:
        shutil.rmtree(safe_dir)
        shutil.rmtree(sensitive_dir)
