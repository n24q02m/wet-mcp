from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from wet_mcp.security import resolve_safe_url
from wet_mcp.sources.crawler import download_media


@pytest.mark.asyncio
async def test_resolve_safe_url_returns_ip():
    # Mock socket.getaddrinfo to return a safe IP
    with patch("socket.getaddrinfo") as mock_dns:
        mock_dns.return_value = [(None, None, None, None, ("8.8.8.8", 80))]
        url = "https://example.com/foo"
        ip_url, hostname, ip = resolve_safe_url(url)
        assert ip == "8.8.8.8"
        assert hostname == "example.com"
        assert ip_url == "https://8.8.8.8/foo"


@pytest.mark.asyncio
async def test_resolve_safe_url_raises_unsafe():
    with patch("socket.getaddrinfo") as mock_dns:
        mock_dns.return_value = [(None, None, None, None, ("127.0.0.1", 80))]
        with pytest.raises(ValueError, match="Blocked private/unsafe IP"):
            resolve_safe_url("http://example.com")


# Test that download_media uses manual redirect loop and SNI extension
@pytest.mark.asyncio
async def test_download_media_uses_pinned_ip():
    # Setup mocks
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.content = b"content"
    mock_response.is_redirect = False

    mock_client_instance = AsyncMock()
    # When build_request is called, return a mock request
    mock_request = MagicMock()
    # Explicitly set build_request as a MagicMock (sync)
    mock_client_instance.build_request = MagicMock(return_value=mock_request)

    # When send is called, return the response
    mock_client_instance.send.return_value = mock_response

    # Mock AsyncClient context manager
    mock_client_cls = MagicMock()
    mock_client_cls.return_value.__aenter__.return_value = mock_client_instance
    mock_client_cls.return_value.__aexit__.return_value = None

    # We mock resolve_safe_url to return a fixed IP
    with (
        patch("wet_mcp.sources.crawler.resolve_safe_url") as mock_resolve,
        patch("pathlib.Path.mkdir"),
        patch("pathlib.Path.write_bytes"),
        patch("httpx.AsyncClient", mock_client_cls),
    ):
        mock_resolve.return_value = (
            "https://9.9.9.9/file.jpg",
            "example.com",
            "9.9.9.9",
        )

        await download_media(["https://example.com/file.jpg"], "/tmp")

        # Verify resolve_safe_url was called
        mock_resolve.assert_called_with("https://example.com/file.jpg")

        # Verify build_request was called with IP url and SNI extension
        mock_client_instance.build_request.assert_called_with(
            "GET",
            "https://9.9.9.9/file.jpg",
            headers={"Host": "example.com"},
            extensions={"sni_hostname": "example.com"},
        )

        # Verify send was called with follow_redirects=False
        mock_client_instance.send.assert_called_with(
            mock_request, follow_redirects=False
        )
