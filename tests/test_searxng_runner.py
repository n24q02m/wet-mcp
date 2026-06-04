"""Tests for SearXNG runner wrapper (delegates to web-core).

Tests the wet-mcp wrapper layer that bridges settings to web-core's API.
Internal SearXNG process management is tested in web-core's test suite.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from wet_mcp.searxng_runner import _find_available_port, ensure_searxng, stop_searxng


@pytest.fixture
def mock_settings():
    with patch("wet_mcp.searxng_runner.settings") as mock:
        mock.wet_auto_searxng = True
        mock.searxng_url = "http://external:8080"
        mock.wet_searxng_port = 8080
        yield mock


@pytest.fixture
def mock_wc_ensure():
    """Mock web-core's ensure_searxng at the delegation boundary."""
    with patch(
        "wet_mcp.searxng_runner._wc_runner.ensure_searxng",
        new_callable=AsyncMock,
    ) as mock:
        yield mock


async def test_ensure_searxng_auto_disabled(mock_settings):
    """When auto-start disabled, return external URL without calling web-core."""
    mock_settings.wet_auto_searxng = False

    url = await ensure_searxng()

    assert url == "http://external:8080"


async def test_ensure_searxng_delegates_to_web_core(mock_settings, mock_wc_ensure):
    """When auto-start enabled, delegate to web-core with correct params."""
    mock_settings.wet_searxng_port = 9090
    mock_wc_ensure.return_value = "http://127.0.0.1:9090"

    url = await ensure_searxng()

    assert url == "http://127.0.0.1:9090"
    mock_wc_ensure.assert_called_once_with(start_port=9090)


async def test_ensure_searxng_fallback_on_error(mock_settings, mock_wc_ensure):
    """When web-core raises RuntimeError, fall back to external URL."""
    mock_wc_ensure.side_effect = RuntimeError("SearXNG start failed")

    url = await ensure_searxng()

    assert url == "http://external:8080"


async def test_ensure_searxng_passes_configured_port(mock_settings, mock_wc_ensure):
    """Verify wet_searxng_port setting is forwarded as start_port."""
    mock_settings.wet_searxng_port = 12345
    mock_wc_ensure.return_value = "http://127.0.0.1:12345"

    await ensure_searxng()

    mock_wc_ensure.assert_called_once_with(start_port=12345)


def test_stop_searxng_delegates():
    """stop_searxng should call web-core's shutdown_searxng."""
    with patch("wet_mcp.searxng_runner.shutdown_searxng") as mock_shutdown:
        stop_searxng()
        mock_shutdown.assert_called_once()


def test_patched_installer_calls_patches():
    """Verify monkey-patched installer applies wet-mcp patches after install."""
    with (
        patch("wet_mcp.searxng_runner._wc_original_install", return_value=True),
        patch("wet_mcp.setup.patch_searxng_version") as mock_version,
        patch("wet_mcp.setup.patch_searxng_windows") as mock_windows,
    ):
        from wet_mcp.searxng_runner import _patched_install_searxng

        result = _patched_install_searxng()

        assert result is True
        mock_version.assert_called_once()
        mock_windows.assert_called_once()


def test_patched_installer_skips_patches_on_failure():
    """If web-core install fails, patches are not applied."""
    with (
        patch("wet_mcp.searxng_runner._wc_original_install", return_value=False),
        patch("wet_mcp.setup.patch_searxng_version") as mock_version,
        patch("wet_mcp.setup.patch_searxng_windows") as mock_windows,
    ):
        from wet_mcp.searxng_runner import _patched_install_searxng

        result = _patched_install_searxng()

        assert result is False
        mock_version.assert_not_called()
        mock_windows.assert_not_called()


def test_find_available_port_success():
    """Verify _find_available_port returns a port when bind succeeds."""
    with (
        patch("socket.socket") as mock_socket,
        patch("random.shuffle"),
    ):
        # mock_socket() returns a context manager that returns mock_s
        mock_s = MagicMock()
        mock_socket.return_value.__enter__.return_value = mock_s

        # Success on first try (offset 0 if shuffle is mocked to do nothing)
        port = _find_available_port(8080, max_tries=1)

        assert port == 8080
        mock_s.bind.assert_called_once_with(("127.0.0.1", 8080))


def test_find_available_port_retry():
    """Verify _find_available_port retries when bind fails."""
    with (
        patch("socket.socket") as mock_socket,
        patch("random.shuffle"),
    ):
        mock_s = MagicMock()
        mock_socket.return_value.__enter__.return_value = mock_s

        # Fail first try, succeed second
        mock_s.bind.side_effect = [OSError("Port in use"), None]

        # Use max_tries=2 and ensure deterministic order by mocking shuffle
        # Default offsets are [0, 1]
        port = _find_available_port(8080, max_tries=2)

        assert port in [8080, 8081]
        assert mock_s.bind.call_count == 2


def test_find_available_port_failure():
    """Verify _find_available_port raises RuntimeError when no ports available."""
    with (
        patch("socket.socket") as mock_socket,
        patch("random.shuffle"),
    ):
        mock_s = MagicMock()
        mock_socket.return_value.__enter__.return_value = mock_s

        mock_s.bind.side_effect = OSError("Port in use")

        with pytest.raises(RuntimeError, match="No available port found"):
            _find_available_port(8080, max_tries=5)

        assert mock_s.bind.call_count == 5
