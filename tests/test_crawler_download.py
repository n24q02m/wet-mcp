import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from wet_mcp.sources.crawler import download_media


@pytest.mark.asyncio
async def test_download_media_success(tmp_path):
    """Test successful download of media files."""
    mock_content = b"test content"

    mock_response = MagicMock()
    mock_response.is_redirect = False
    mock_response.content = mock_content
    mock_response.raise_for_status = MagicMock()
    mock_response.headers = {}

    # The client used inside the with block
    mock_client = AsyncMock()
    mock_client.get.return_value = mock_response

    # The context manager instance returned by httpx.AsyncClient()
    mock_client_instance = AsyncMock()
    mock_client_instance.__aenter__.return_value = mock_client
    mock_client_instance.__aexit__.return_value = None

    # The class/constructor httpx.AsyncClient
    mock_client_cls = MagicMock(return_value=mock_client_instance)

    url = "http://example.com/file.txt"
    output_dir = str(tmp_path)

    with patch("wet_mcp.sources.crawler._safe_httpx_client", mock_client_cls):
        result_json = await download_media([url], output_dir)

    results = json.loads(result_json)

    # Verify file was written
    expected_file = tmp_path / "file.txt"
    assert expected_file.exists()
    assert expected_file.read_bytes() == mock_content

    # Verify result JSON
    assert len(results) == 1
    assert results[0]["url"] == url
    assert results[0]["path"] == str(expected_file)
    assert results[0]["size"] == len(mock_content)

    # Verify client usage
    mock_client.get.assert_called_once()
    args, kwargs = mock_client.get.call_args
    assert args[0] == url


@pytest.mark.asyncio
async def test_download_media_protocol_relative(tmp_path):
    """Test handling of protocol-relative URLs."""
    mock_content = b"image data"

    mock_response = MagicMock()
    mock_response.is_redirect = False
    mock_response.content = mock_content
    mock_response.raise_for_status = MagicMock()
    mock_response.headers = {}

    mock_client = AsyncMock()
    mock_client.get.return_value = mock_response

    mock_client_instance = AsyncMock()
    mock_client_instance.__aenter__.return_value = mock_client
    mock_client_instance.__aexit__.return_value = None

    mock_client_cls = MagicMock(return_value=mock_client_instance)

    url = "//example.com/image.jpg"
    output_dir = str(tmp_path)

    with patch("wet_mcp.sources.crawler._safe_httpx_client", mock_client_cls):
        result_json = await download_media([url], output_dir)

    results = json.loads(result_json)

    # Verify file was written
    expected_file = tmp_path / "image.jpg"
    assert expected_file.exists()
    assert expected_file.read_bytes() == mock_content

    # Verify client called with https prefix
    mock_client.get.assert_called_once()
    args, kwargs = mock_client.get.call_args
    assert args[0] == "https://example.com/image.jpg"

    assert results[0]["url"] == url
    assert results[0]["path"] == str(expected_file)


@pytest.mark.asyncio
async def test_download_media_http_error(tmp_path):
    """Test handling of HTTP errors during download."""
    mock_response = MagicMock()
    mock_response.is_redirect = False
    mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
        "404 Not Found",
        request=httpx.Request("GET", "http://example.com/missing.txt"),
        response=httpx.Response(
            404, request=httpx.Request("GET", "http://example.com/missing.txt")
        ),
    )

    mock_client = AsyncMock()
    mock_client.get.return_value = mock_response

    mock_client_instance = AsyncMock()
    mock_client_instance.__aenter__.return_value = mock_client
    mock_client_instance.__aexit__.return_value = None

    mock_client_cls = MagicMock(return_value=mock_client_instance)

    url = "http://example.com/missing.txt"

    with patch("wet_mcp.sources.crawler._safe_httpx_client", mock_client_cls):
        result_json = await download_media([url], str(tmp_path))

    results = json.loads(result_json)

    assert len(results) == 1
    assert results[0]["url"] == url
    assert "error" in results[0]
    assert "404 Not Found" in results[0]["error"]

    # File should not exist
    assert not (tmp_path / "missing.txt").exists()


@pytest.mark.asyncio
async def test_download_media_file_write_error(tmp_path):
    """Test handling of file write errors."""
    mock_content = b"test content"

    mock_response = MagicMock()
    mock_response.is_redirect = False
    mock_response.content = mock_content
    mock_response.raise_for_status = MagicMock()
    mock_response.headers = {}

    mock_client = AsyncMock()
    mock_client.get.return_value = mock_response

    mock_client_instance = AsyncMock()
    mock_client_instance.__aenter__.return_value = mock_client
    mock_client_instance.__aexit__.return_value = None

    mock_client_cls = MagicMock(return_value=mock_client_instance)

    url = "http://example.com/file.txt"

    with patch("wet_mcp.sources.crawler._safe_httpx_client", mock_client_cls):
        with patch(
            "pathlib.Path.write_bytes", side_effect=PermissionError("Access denied")
        ):
            result_json = await download_media([url], str(tmp_path))

    results = json.loads(result_json)

    assert len(results) == 1
    assert results[0]["url"] == url
    assert "error" in results[0]
    assert "Access denied" in results[0]["error"]


@pytest.mark.asyncio
async def test_download_media_unsafe_redirect(tmp_path):
    """Test that download_media blocks unsafe URLs during redirect."""
    mock_client = AsyncMock()

    # First response is a redirect to an unsafe URL
    mock_response_1 = MagicMock()
    mock_response_1.is_redirect = True
    mock_response_1.headers = {"Location": "http://169.254.169.254/metadata"}

    mock_client.get.return_value = mock_response_1

    mock_client_instance = AsyncMock()
    mock_client_instance.__aenter__.return_value = mock_client
    mock_client_instance.__aexit__.return_value = None
    mock_client_cls = MagicMock(return_value=mock_client_instance)

    url = "http://example.com/redirect-to-unsafe"

    # We need to mock is_safe_url to return False for the second URL
    def side_effect_is_safe(u):
        if "169.254" in u:
            return False
        return True

    with patch("wet_mcp.sources.crawler._safe_httpx_client", mock_client_cls):
        with patch(
            "wet_mcp.sources.crawler.is_safe_url", side_effect=side_effect_is_safe
        ):
            result_json = await download_media([url], str(tmp_path))

    results = json.loads(result_json)
    assert len(results) == 1
    assert results[0]["url"] == url
    assert "error" in results[0]
    assert "Security Alert: Unsafe URL blocked" in results[0]["error"]
    # Should only call get once because the second URL is blocked before the call
    assert mock_client.get.call_count == 1


@pytest.mark.asyncio
async def test_download_media_missing_location_header(tmp_path):
    """Test handling of redirect without Location header."""
    mock_client = AsyncMock()

    mock_response = MagicMock()
    mock_response.is_redirect = True
    mock_response.headers = {}  # No Location
    mock_response.content = b"redirect page content"
    mock_response.raise_for_status = MagicMock()

    mock_client.get.return_value = mock_response

    mock_client_instance = AsyncMock()
    mock_client_instance.__aenter__.return_value = mock_client
    mock_client_instance.__aexit__.return_value = None
    mock_client_cls = MagicMock(return_value=mock_client_instance)

    url = "http://example.com/bad-redirect"

    with patch("wet_mcp.sources.crawler._safe_httpx_client", mock_client_cls):
        result_json = await download_media([url], str(tmp_path))

    results = json.loads(result_json)
    assert len(results) == 1
    assert "path" in results[0]  # It should have downloaded the redirect page
    assert Path(results[0]["path"]).name == "bad-redirect"


@pytest.mark.asyncio
async def test_download_media_extension_inference(tmp_path):
    """Test inferring extension from Content-Type."""
    mock_client = AsyncMock()

    mock_response = MagicMock()
    mock_response.is_redirect = False
    # Use lowercase "content-type" as that's what the code uses: response.headers.get("content-type", "")
    mock_response.headers = {"content-type": "image/png"}
    mock_response.content = b"fake png data"
    mock_response.raise_for_status = MagicMock()

    mock_client.get.return_value = mock_response

    mock_client_instance = AsyncMock()
    mock_client_instance.__aenter__.return_value = mock_client
    mock_client_instance.__aexit__.return_value = None
    mock_client_cls = MagicMock(return_value=mock_client_instance)

    url = "http://example.com/image-no-ext"

    with patch("wet_mcp.sources.crawler._safe_httpx_client", mock_client_cls):
        result_json = await download_media([url], str(tmp_path))

    results = json.loads(result_json)
    assert len(results) == 1
    assert results[0]["path"].endswith(".png")
    assert Path(results[0]["path"]).name == "image-no-ext.png"


@pytest.mark.asyncio
async def test_download_media_path_traversal_detection(tmp_path):
    """Test path traversal detection."""
    mock_client = AsyncMock()

    mock_response = MagicMock()
    mock_response.is_redirect = False
    mock_response.content = b"content"
    mock_response.raise_for_status = MagicMock()

    mock_client.get.return_value = mock_response

    mock_client_instance = AsyncMock()
    mock_client_instance.__aenter__.return_value = mock_client
    mock_client_instance.__aexit__.return_value = None
    mock_client_cls = MagicMock(return_value=mock_client_instance)

    url = "http://example.com/file.txt"

    with patch("wet_mcp.sources.crawler._safe_httpx_client", mock_client_cls):
        mock_filepath = MagicMock(spec=Path)
        mock_filepath.resolve.return_value = Path("/etc/passwd")
        mock_filepath.is_relative_to.return_value = False

        with patch.object(Path, "__truediv__", return_value=mock_filepath):
            result_json = await download_media([url], str(tmp_path))

    results = json.loads(result_json)
    assert len(results) == 1
    assert "error" in results[0]
    assert "Security Alert: Path traversal attempt detected" in results[0]["error"]


@pytest.mark.asyncio
async def test_download_media_generic_exception(tmp_path):
    """Test handling of generic exceptions."""
    mock_client = AsyncMock()
    mock_client.get.side_effect = RuntimeError("Something went wrong")

    mock_client_instance = AsyncMock()
    mock_client_instance.__aenter__.return_value = mock_client
    mock_client_instance.__aexit__.return_value = None
    mock_client_cls = MagicMock(return_value=mock_client_instance)

    url = "http://example.com/fail"

    with patch("wet_mcp.sources.crawler._safe_httpx_client", mock_client_cls):
        result_json = await download_media([url], str(tmp_path))

    results = json.loads(result_json)
    assert len(results) == 1
    assert "error" in results[0]
    assert "Something went wrong" in results[0]["error"]


@pytest.mark.asyncio
async def test_download_media_max_redirects(tmp_path):
    """Test hitting max redirects limit."""
    mock_client = AsyncMock()

    # Always redirect
    mock_response = MagicMock()
    mock_response.is_redirect = True
    mock_response.headers = {"Location": "http://example.com/loop"}

    mock_client.get.return_value = mock_response

    mock_client_instance = AsyncMock()
    mock_client_instance.__aenter__.return_value = mock_client
    mock_client_instance.__aexit__.return_value = None
    mock_client_cls = MagicMock(return_value=mock_client_instance)

    url = "http://example.com/redirect-loop"

    with patch("wet_mcp.sources.crawler._safe_httpx_client", mock_client_cls):
        result_json = await download_media([url], str(tmp_path))

    results = json.loads(result_json)
    assert len(results) == 1
    assert "path" in results[0] or "error" in results[0]
