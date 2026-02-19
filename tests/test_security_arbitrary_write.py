from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from wet_mcp.config import Settings
from wet_mcp.sources.crawler import download_media


@pytest.mark.asyncio
async def test_arbitrary_file_write_vulnerability(tmp_path):
    """
    Reproduce Arbitrary File Write vulnerability.
    We attempt to download a file to a directory outside the intended 'safe' area.
    """
    # 1. Setup
    # Create a safe base directory (simulating configured download_dir)
    safe_root = tmp_path / "safe_downloads"
    safe_root.mkdir()

    # Create a sensitive directory OUTSIDE safe_root
    sensitive_dir = tmp_path / "sensitive_data"
    sensitive_dir.mkdir()

    # 2. Mock network calls
    mock_response = MagicMock()
    mock_response.content = b"malicious content"
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.get.return_value = mock_response
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = None

    # Use a real Settings object for the patch
    test_settings = Settings(download_dir=str(safe_root))

    # Mock settings to enforce safe_root as the allowed download dir
    with patch("wet_mcp.sources.crawler.settings", test_settings):
        # Mock is_safe_url to pass so we focus on path validation
        with patch("wet_mcp.sources.crawler.is_safe_url", return_value=True):
            with patch("httpx.AsyncClient", return_value=mock_client):
                url = "http://example.com/exploit.txt"

                # 3. Execute with sensitive_dir as output_dir
                # Expect ValueError due to security check
                with pytest.raises(ValueError, match="Security Alert"):
                    await download_media([url], str(sensitive_dir))

    # 4. Verify Exploit Failed
    exploit_file = sensitive_dir / "exploit.txt"
    assert not exploit_file.exists(), (
        "Vulnerability still exists! File was written to sensitive directory."
    )
    print("\n[SECURE] File write blocked successfully.")
