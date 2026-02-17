from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from wet_mcp.config import settings
from wet_mcp.llm import analyze_media
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

    # We need to simulate is_safe_url passing for these URLs, or mock it.
    # Since we are testing path traversal, we assume the URL is "safe" network-wise but malicious filename-wise.
    # But wait, is_safe_url checks scheme and IP.
    # "http://example.com/.." is safe network-wise (resolves to example.com IP).

    with patch("wet_mcp.sources.crawler.is_safe_url", return_value=True):
        with patch("httpx.AsyncClient", return_value=mock_client):
            # 1. Traversal attempt with '..' as filename
            # This simulates a URL where split('/')[-1] is '..'
            url1 = "http://example.com/.."
            res1 = await download_media([url1], str(tmp_path))

            # Should fail with "Security Alert" because '..' resolves to parent dir
            assert "Security Alert" in res1

            # Verify no files were written in parent
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


@pytest.mark.asyncio
async def test_analyze_media_path_traversal(tmp_path):
    """Test that analyze_media prevents path traversal."""
    # Setup directories
    download_dir = tmp_path / "downloads"
    download_dir.mkdir()

    # Create a secret file outside download_dir
    secret_file = tmp_path / "secret.txt"
    secret_content = "This is a secret file"
    secret_file.write_text(secret_content)

    # Configure settings
    original_download_dir = settings.download_dir
    original_api_keys = settings.api_keys
    settings.download_dir = str(download_dir)
    settings.api_keys = "fake-provider:fake-key"

    try:
        # Mock LLM response
        with patch("wet_mcp.llm.acompletion") as mock_completion:
            mock_response = MagicMock()
            mock_response.choices[0].message.content = "Analysis result"
            mock_completion.return_value = mock_response

            # Call analyze_media with the secret file path
            result = await analyze_media(str(secret_file))

            # Verify that the file was NOT read
            assert "Security Alert" in result
            assert secret_content not in result

            # Verify LLM was NOT called with secret content
            if mock_completion.called:
                call_args = mock_completion.call_args[1]
                messages = call_args.get("messages", [])
                if messages:
                    content_sent = messages[0]["content"]
                    assert secret_content not in content_sent
    finally:
        settings.download_dir = original_download_dir
        settings.api_keys = original_api_keys
