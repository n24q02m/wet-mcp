"""Unit tests for setup utilities."""

from unittest.mock import patch, MagicMock
import sys

import pytest

# Mock dependencies that might be missing in the test environment

# Mock mcp
mcp_mock = MagicMock()
sys.modules["mcp"] = mcp_mock
sys.modules["mcp.server"] = MagicMock()
sys.modules["mcp.server.fastmcp"] = MagicMock()
sys.modules["mcp.types"] = MagicMock()

# Mock loguru
sys.modules["loguru"] = MagicMock()

# Mock pydantic and pydantic_settings
sys.modules["pydantic"] = MagicMock()
sys.modules["pydantic_settings"] = MagicMock()

# Mock other potential imports
sys.modules["httpx"] = MagicMock()
sys.modules["bs4"] = MagicMock()
sys.modules["crawl4ai"] = MagicMock()
sys.modules["litellm"] = MagicMock()
sys.modules["playwright"] = MagicMock()
sys.modules["playwright.async_api"] = MagicMock()
sys.modules["numpy"] = MagicMock()
sys.modules["faiss"] = MagicMock()

# Mock importlib.metadata to avoid PackageNotFoundError
with patch("importlib.metadata.version", return_value="0.0.0"):
    try:
        from wet_mcp.setup import patch_searxng_version  # noqa: F401
    except ImportError:
        pass

@pytest.fixture(autouse=True)
def _reset_crawler_singleton():
    """Override conftest fixture to avoid async issues in sync tests."""
    yield

@pytest.fixture
def mock_logger():
    """Mock loguru logger."""
    if "wet_mcp.setup" in sys.modules:
        mod = sys.modules["wet_mcp.setup"]
        mock = mod.logger
        mock.reset_mock()
        return mock
    else:
        # Fallback
        return MagicMock()

def test_patch_searxng_version_creates_file(tmp_path, mock_logger):
    """Test that version_frozen.py is created if it doesn't exist."""
    # Re-import to ensure we have the module
    with patch("importlib.metadata.version", return_value="0.0.0"):
         from wet_mcp.setup import patch_searxng_version  # noqa: F401

    # Setup: searx_dir is tmp_path
    with patch("wet_mcp.setup._find_searx_package_dir", return_value=tmp_path):
        patch_searxng_version()

    vf = tmp_path / "version_frozen.py"
    assert vf.exists()
    content = vf.read_text()
    assert 'VERSION_STRING = "0.0.0"' in content
    assert 'GIT_URL = "https://github.com/searxng/searxng"' in content

    mock_logger.debug.assert_called_with(f"Created SearXNG version_frozen: {vf}")


def test_patch_searxng_version_skips_existing(tmp_path, mock_logger):
    """Test that version_frozen.py is NOT overwritten if it exists."""
    with patch("importlib.metadata.version", return_value="0.0.0"):
         from wet_mcp.setup import patch_searxng_version  # noqa: F401

    vf = tmp_path / "version_frozen.py"
    original_content = 'VERSION_STRING = "9.9.9"'
    vf.write_text(original_content)

    with patch("wet_mcp.setup._find_searx_package_dir", return_value=tmp_path):
        patch_searxng_version()

    assert vf.read_text() == original_content
    mock_logger.debug.assert_not_called()


def test_patch_searxng_version_no_package(mock_logger):
    """Test that nothing happens if searx package is not found."""
    with patch("importlib.metadata.version", return_value="0.0.0"):
         from wet_mcp.setup import patch_searxng_version  # noqa: F401

    with patch("wet_mcp.setup._find_searx_package_dir", return_value=None):
        patch_searxng_version()

    mock_logger.debug.assert_not_called()
    mock_logger.warning.assert_not_called()


def test_patch_searxng_version_handles_error(mock_logger):
    """Test that exceptions are caught and logged."""
    with patch("importlib.metadata.version", return_value="0.0.0"):
         from wet_mcp.setup import patch_searxng_version  # noqa: F401

    # Simulate an error by making _find_searx_package_dir raise an exception
    with patch("wet_mcp.setup._find_searx_package_dir", side_effect=Exception("Test Error")):
        patch_searxng_version()

    mock_logger.warning.assert_called_once()
    assert "Test Error" in str(mock_logger.warning.call_args)
