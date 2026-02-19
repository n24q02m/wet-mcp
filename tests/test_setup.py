import sys
from unittest.mock import MagicMock, patch

import pytest

# Import module to patch globals
from wet_mcp.setup import (
    _install_searxng,
    _setup_crawl4ai,
    needs_setup,
    patch_searxng_version,
    reset_setup,
    run_auto_setup,
)


@pytest.fixture
def mock_home(tmp_path):
    """Mock Path.home() and SETUP_MARKER to return a temp directory."""
    # Patch Path.home for any new calls
    with patch("pathlib.Path.home", return_value=tmp_path):
        # Patch the global SETUP_MARKER in the module
        new_marker = tmp_path / ".wet-mcp" / ".setup-complete"
        with patch("wet_mcp.setup.SETUP_MARKER", new_marker):
            yield tmp_path


@pytest.fixture
def mock_subprocess():
    """Mock subprocess.run."""
    with patch("subprocess.run") as mock_run:
        # Default success
        mock_run.return_value.returncode = 0
        yield mock_run


def test_needs_setup(mock_home):
    """Test setup marker check."""
    # Marker doesn't exist yet
    assert needs_setup() is True

    # Create marker
    marker = mock_home / ".wet-mcp" / ".setup-complete"
    marker.parent.mkdir()
    marker.touch()

    assert needs_setup() is False


def test_reset_setup(mock_home):
    """Test setup marker reset."""
    marker = mock_home / ".wet-mcp" / ".setup-complete"
    marker.parent.mkdir()
    marker.touch()

    assert marker.exists()
    reset_setup()
    assert not marker.exists()


def test_install_searxng_already_installed():
    """Test _install_searxng when searx is importable."""
    with patch.dict(sys.modules, {"searx": MagicMock()}):
        assert _install_searxng() is True


def test_install_searxng_install_success(mock_subprocess):
    """Test _install_searxng installation flow."""
    # Simulate searx not installed
    with patch.dict(sys.modules):
        sys.modules.pop("searx", None)
        with patch("wet_mcp.setup.patch_searxng_version") as mock_patch_ver:
            with patch("wet_mcp.setup.patch_searxng_windows") as mock_patch_win:
                assert _install_searxng() is True
                assert mock_subprocess.call_count == 2  # deps + package
                mock_patch_ver.assert_called_once()
                mock_patch_win.assert_called_once()


def test_install_searxng_install_failure(mock_subprocess):
    """Test _install_searxng installation failure."""
    # Simulate deps install failure
    mock_subprocess.return_value.returncode = 1
    with patch.dict(sys.modules):
        sys.modules.pop("searx", None)
        assert _install_searxng() is False


def test_setup_crawl4ai_success():
    """Test _setup_crawl4ai success."""
    with patch("crawl4ai.install.post_install") as mock_post_install:
        assert _setup_crawl4ai() is True
        mock_post_install.assert_called_once()


def test_setup_crawl4ai_failure():
    """Test _setup_crawl4ai failure."""
    with patch("crawl4ai.install.post_install", side_effect=Exception("Boom")):
        assert _setup_crawl4ai() is False


def test_run_auto_setup_success(mock_home):
    """Test run_auto_setup full flow."""
    with patch("wet_mcp.setup._install_searxng", return_value=True) as mock_install:
        with patch("wet_mcp.setup._setup_crawl4ai", return_value=True) as mock_c4ai:
            assert run_auto_setup() is True

            # Check marker created
            marker = mock_home / ".wet-mcp" / ".setup-complete"
            assert marker.exists()

            mock_install.assert_called_once()
            mock_c4ai.assert_called_once()


def test_run_auto_setup_already_done(mock_home):
    """Test run_auto_setup skips if done."""
    marker = mock_home / ".wet-mcp" / ".setup-complete"
    marker.parent.mkdir()
    marker.touch()

    with patch("wet_mcp.setup._install_searxng") as mock_install:
        # Also mock _setup_crawl4ai to be safe, though it shouldn't be called
        with patch("wet_mcp.setup._setup_crawl4ai") as mock_c4ai:
            assert run_auto_setup() is True
            mock_install.assert_not_called()
            mock_c4ai.assert_not_called()


def test_patch_searxng_version(tmp_path):
    """Test patching searxng version."""
    searx_dir = tmp_path / "searx"
    searx_dir.mkdir()

    with patch("importlib.util.find_spec") as mock_spec:
        mock_spec.return_value.submodule_search_locations = [str(searx_dir)]

        patch_searxng_version()

        vf = searx_dir / "version_frozen.py"
        assert vf.exists()
        assert 'VERSION_TAG = "v0.0.0"' in vf.read_text()
