"""Tests for ``media(action="analyze")`` deprecation (Phase 1, Task 6).

Locks in the deprecation contract:

- analyze returns a stable migration string (not a generic error).
- analyze emits a logger.warning so callers can be located via logs.
- list + download backwards-compat: the deprecation does not regress them.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from wet_mcp.server import media


@pytest.mark.asyncio
async def test_media_analyze_returns_deprecation_string() -> None:
    result = await media(action="analyze", url="/tmp/x.jpg", prompt="hi")
    assert isinstance(result, str)
    assert "deprecated" in result
    assert "imagine-mcp" in result
    assert "v2.0.0" in result


@pytest.mark.asyncio
async def test_media_analyze_logs_warning() -> None:
    # loguru-based logger -- patch the wet_mcp.server.logger directly so
    # we don't need a loguru<->logging bridge in the test.
    with patch("wet_mcp.server.logger") as mock_logger:
        await media(action="analyze")
        assert mock_logger.warning.called
        msg = mock_logger.warning.call_args.args[0]
        assert "deprecated" in msg
        assert "imagine-mcp" in msg


@pytest.mark.asyncio
async def test_media_analyze_does_not_invoke_analyze_media() -> None:
    mocked = AsyncMock(return_value="should not run")
    with patch("wet_mcp.llm.analyze_media", mocked):
        result = await media(action="analyze", url="/tmp/x.jpg")
        mocked.assert_not_called()
        assert "deprecated" in result


@pytest.mark.asyncio
async def test_media_list_still_works_after_deprecation() -> None:
    """Backward compat: list keeps its existing contract."""
    with patch(
        "wet_mcp.server.list_media",
        new_callable=AsyncMock,
        return_value='{"images": [{"src": "https://x/y.jpg"}]}',
    ):
        result = await media(action="list", url="https://example.com/gallery")
        assert "images" in result
        assert "deprecated" not in result


@pytest.mark.asyncio
async def test_media_download_still_works_after_deprecation(tmp_path) -> None:
    """Backward compat: download keeps its existing contract."""
    download_dir = tmp_path / "downloads"
    download_dir.mkdir()

    with (
        patch("wet_mcp.server.settings.download_dir", str(download_dir)),
        patch(
            "wet_mcp.sources.crawler.download_media",
            new_callable=AsyncMock,
            return_value='[{"url": "https://x/y.jpg", "path": "/tmp/y.jpg"}]',
        ),
    ):
        result = await media(
            action="download",
            media_urls=["https://example.com/img.jpg"],
            output_dir=str(download_dir),
        )
        assert "y.jpg" in result
        assert "deprecated" not in result


# Sanity import.
def test_module_imports() -> None:
    from wet_mcp import server  # noqa: F401


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
