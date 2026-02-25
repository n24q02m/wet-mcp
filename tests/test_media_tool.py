from unittest.mock import AsyncMock, patch

import pytest

from wet_mcp.server import media


@pytest.fixture
def mock_settings():
    with patch("wet_mcp.server.settings") as mock_settings:
        mock_settings.tool_timeout = 0  # Disable timeout for faster tests
        mock_settings.download_dir = "/tmp/downloads"
        mock_settings.log_level = "INFO"
        yield mock_settings


@pytest.mark.asyncio
async def test_media_list_success(mock_settings):
    """Test media list action successfully calls list_media."""
    mock_list_media = AsyncMock(return_value='{"images": []}')

    with patch("wet_mcp.server.list_media", mock_list_media):
        result = await media(
            action="list", url="http://example.com", media_type="images", max_items=5
        )

        mock_list_media.assert_called_once_with(
            url="http://example.com", media_type="images", max_items=5
        )
        assert '{"images": []}' in result
        assert "<untrusted_media_content>" in result
        assert "[SECURITY:" in result


@pytest.mark.asyncio
async def test_media_list_missing_url():
    """Test media list action fails without url."""
    result = await media(action="list")
    assert result == "Error: url is required for list action"


@pytest.mark.asyncio
async def test_media_download_success(mock_settings):
    """Test media download action successfully calls download_media."""
    mock_download_media = AsyncMock(return_value='["file1.jpg"]')

    with patch("wet_mcp.sources.crawler.download_media", mock_download_media):
        result = await media(
            action="download",
            media_urls=["http://example.com/img.jpg"],
            output_dir="/custom/dir",
        )

        mock_download_media.assert_called_once_with(
            media_urls=["http://example.com/img.jpg"], output_dir="/custom/dir"
        )
        assert '["file1.jpg"]' in result
        assert "<untrusted_media_content>" in result


@pytest.mark.asyncio
async def test_media_download_default_dir(mock_settings):
    """Test media download action uses default directory if not provided."""
    mock_download_media = AsyncMock(return_value='["file1.jpg"]')

    with patch("wet_mcp.sources.crawler.download_media", mock_download_media):
        result = await media(
            action="download", media_urls=["http://example.com/img.jpg"]
        )

        mock_download_media.assert_called_once_with(
            media_urls=["http://example.com/img.jpg"],
            output_dir=mock_settings.download_dir,
        )
        assert '["file1.jpg"]' in result
        assert "<untrusted_media_content>" in result


@pytest.mark.asyncio
async def test_media_download_missing_urls():
    """Test media download action fails without media_urls."""
    result = await media(action="download")
    assert result == "Error: media_urls is required for download action"


@pytest.mark.asyncio
async def test_media_analyze_success(mock_settings):
    """Test media analyze action successfully calls analyze_media."""
    mock_analyze_media = AsyncMock(return_value="Analysis result")

    with patch("wet_mcp.llm.analyze_media", mock_analyze_media):
        result = await media(
            action="analyze", url="/path/to/image.jpg", prompt="Describe it"
        )

        mock_analyze_media.assert_called_once_with(
            media_path="/path/to/image.jpg", prompt="Describe it"
        )
        assert "Analysis result" in result
        assert "<untrusted_media_content>" in result


@pytest.mark.asyncio
async def test_media_analyze_missing_url():
    """Test media analyze action fails without url (local path)."""
    result = await media(action="analyze")
    assert result == "Error: url (local path) is required for analyze action"


@pytest.mark.asyncio
async def test_media_unknown_action():
    """Test media action with unknown action."""
    result = await media(action="unknown_action")
    assert "Error: Unknown action 'unknown_action'" in result
    assert "Valid actions: list, download, analyze" in result
