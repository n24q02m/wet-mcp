from unittest.mock import AsyncMock, MagicMock, patch

import pytest

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
            # Patch settings.download_dir so tmp_path is accepted
            with patch("wet_mcp.config.settings.download_dir", str(tmp_path)):
                # 1. Traversal attempt with '..' as filename
                # This simulates a URL where split('/')[-1] is '..'
                url1 = "http://example.com/.."

                # Note: We expect this to fail inside the download loop when checking filename,
                # NOT at the output_dir check (since output_dir=tmp_path is valid here).

                res1 = await download_media([url1], str(tmp_path))

                # Should fail with "Security Alert" because '..' resolves to parent dir
                assert "Security Alert" in res1


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
            # Patch settings.download_dir so tmp_path is accepted
            with patch("wet_mcp.config.settings.download_dir", str(tmp_path)):
                url = "http://example.com/image.png"
                await download_media([url], str(tmp_path))

                expected_file = tmp_path / "image.png"
                assert expected_file.exists()
                assert expected_file.read_bytes() == b"safe content"


@pytest.mark.asyncio
async def test_download_media_output_dir_traversal(tmp_path):
    """Test that download_media prevents arbitrary output_dir."""
    from wet_mcp.sources.crawler import download_media

    # We mock is_safe_url to avoid network checks
    with patch("wet_mcp.sources.crawler.is_safe_url", return_value=True):
        # We assume settings.download_dir is set to tmp_path/downloads
        target_download_dir = tmp_path / "downloads"
        target_download_dir.mkdir()

        with patch("wet_mcp.config.settings.download_dir", str(target_download_dir)):
            # 1. Attempt with a path outside downloads
            unsafe_dir = tmp_path / "outside"

            with pytest.raises(
                ValueError, match="Security Alert: Output directory must be within"
            ):
                await download_media(["http://example.com/foo.txt"], str(unsafe_dir))

            assert not unsafe_dir.exists()

            # 2. Attempt with traversal relative to downloads
            unsafe_traversal = target_download_dir / ".." / "outside_via_traversal"

            with pytest.raises(
                ValueError, match="Security Alert: Output directory must be within"
            ):
                await download_media(
                    ["http://example.com/foo.txt"], str(unsafe_traversal)
                )

            # 3. Valid download should pass (output_dir check only)
            valid_dir = target_download_dir / "subdir"

            # Mock httpx to avoid error
            mock_response = MagicMock()
            mock_response.content = b"content"
            mock_response.raise_for_status = MagicMock()
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_response
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None

            with patch("httpx.AsyncClient", return_value=mock_client):
                await download_media(["http://example.com/foo.txt"], str(valid_dir))

            assert valid_dir.exists()
