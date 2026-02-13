import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from wet_mcp.security import is_safe_path
from wet_mcp.sources.crawler import (
    crawl,
    download_media,
    extract,
    list_media,
    sitemap,
)
from wet_mcp.llm import analyze_media


# ---------------------------------------------------------------------------
# Unit Tests: is_safe_path
# ---------------------------------------------------------------------------

def test_is_safe_path_basic(tmp_path):
    """Test basic path safety checks."""
    base = tmp_path / "jail"
    base.mkdir()

    # Safe cases
    assert is_safe_path(base / "file.txt", base)
    assert is_safe_path(base / "subdir" / "file.txt", base)

    # Absolute paths
    assert is_safe_path(str(base / "file.txt"), str(base))


def test_is_safe_path_traversal(tmp_path):
    """Test that path traversal attempts are detected."""
    base = tmp_path / "jail"
    base.mkdir()

    # Unsafe cases
    assert not is_safe_path(base.parent / "passwd", base)
    assert not is_safe_path("/etc/passwd", base)

    # Sneaky traversal
    assert not is_safe_path(base / "../passwd", base)
    assert not is_safe_path(str(base) + "/../passwd", base)


# ---------------------------------------------------------------------------
# Integration Tests: list_media (SSRF)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_media_ssrf():
    """Test that list_media blocks unsafe URLs."""
    with patch("wet_mcp.sources.crawler.is_safe_url", return_value=False) as mock_check:
        result = await list_media("http://unsafe.com")

        mock_check.assert_called_with("http://unsafe.com")
        data = json.loads(result)
        assert "error" in data
        assert "Security Alert" in data["error"]


# ---------------------------------------------------------------------------
# Integration Tests: analyze_media (Path Traversal)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_analyze_media_path_traversal(tmp_path):
    """Test that analyze_media blocks access to files outside download_dir."""
    with patch("wet_mcp.llm.settings") as mock_settings:
        mock_settings.download_dir = str(tmp_path / "downloads")
        mock_settings.api_keys = "dummy"

        # Create a file outside download_dir
        secret_file = tmp_path / "secret.txt"
        secret_file.write_text("secret")

        # Try to access it
        result = await analyze_media(str(secret_file))

        assert "Security Alert" in result
        assert "Access denied" in result


@pytest.mark.asyncio
async def test_analyze_media_safe_access(tmp_path):
    """Test that analyze_media allows access to files inside download_dir."""
    jail = tmp_path / "downloads"
    jail.mkdir()

    safe_file = jail / "image.png"
    safe_file.write_bytes(b"fake image")

    with patch("wet_mcp.llm.settings") as mock_settings:
        mock_settings.download_dir = str(jail)
        mock_settings.api_keys = "dummy"
        mock_settings.llm_models = "gemini/gemini-pro"
        mock_settings.llm_temperature = 0.0

        # Mock LLM calls
        with patch("wet_mcp.llm.get_model_capabilities", return_value={"vision": True, "audio_input": False, "audio_output": False}),              patch("wet_mcp.llm.acompletion", new_callable=AsyncMock) as mock_llm:

            mock_llm.return_value.choices = [MagicMock(message=MagicMock(content="Analysis"))]

            result = await analyze_media(str(safe_file))

            assert result == "Analysis"


# ---------------------------------------------------------------------------
# Parameterized Security Suite
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@pytest.mark.parametrize("func, args", [
    (crawl, (["http://unsafe.com"],)),
    (extract, (["http://unsafe.com"],)),
    (sitemap, (["http://unsafe.com"],)),
])
async def test_crawler_functions_reject_unsafe_urls(func, args):
    """Verify that crawler functions reject unsafe URLs."""
    with patch("wet_mcp.sources.crawler.is_safe_url", return_value=False):
        # Mock crawler to ensure it's not used
        with patch("wet_mcp.sources.crawler._get_crawler", new_callable=AsyncMock):
             result = await func(*args)

             data = json.loads(result)
             # Should be empty list or error
             if isinstance(data, list):
                 if len(data) > 0: assert all("Security Alert" in item.get("error", "") for item in data)
             elif isinstance(data, dict):
                 assert "Security Alert" in data.get("error", "")


@pytest.mark.asyncio
async def test_download_media_rejects_unsafe(tmp_path):
    """Verify download_media rejects unsafe URLs."""
    with patch("wet_mcp.sources.crawler.is_safe_url", return_value=False):
        result = await download_media(["http://unsafe.com"], str(tmp_path))
        data = json.loads(result)
        assert len(data) == 1
        assert "Security Alert" in data[0]["error"]
