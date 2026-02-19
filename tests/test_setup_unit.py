import sys
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest

# We need to import the module under test
# But some functions use top-level imports or local imports that we need to control.

from wet_mcp.setup import (
    SETUP_MARKER,
    _find_searx_package_dir,
    patch_searxng_version,
    patch_searxng_windows,
    needs_setup,
    _install_searxng,
    _setup_crawl4ai,
    run_auto_setup,
    reset_setup,
)

# --- Helper Tests ---

def test_needs_setup():
    with patch("wet_mcp.setup.SETUP_MARKER") as mock_marker:
        mock_marker.exists.return_value = False
        assert needs_setup() is True

        mock_marker.exists.return_value = True
        assert needs_setup() is False

def test_reset_setup():
    with patch("wet_mcp.setup.SETUP_MARKER") as mock_marker:
        mock_marker.exists.return_value = True
        reset_setup()
        mock_marker.unlink.assert_called_once()

        mock_marker.reset_mock()
        mock_marker.exists.return_value = False
        reset_setup()
        mock_marker.unlink.assert_not_called()

def test_find_searx_package_dir():
    # Mock importlib.util.find_spec
    with patch("importlib.util.find_spec") as mock_find_spec:
        # Case 1: Found
        mock_spec = MagicMock()
        mock_spec.submodule_search_locations = ["/path/to/searx"]
        mock_find_spec.return_value = mock_spec

        assert _find_searx_package_dir() == Path("/path/to/searx")

        # Case 2: Not found (spec is None)
        mock_find_spec.return_value = None
        assert _find_searx_package_dir() is None

        # Case 3: Exception
        mock_find_spec.side_effect = Exception("Import error")
        assert _find_searx_package_dir() is None

def test_patch_searxng_version():
    with patch("wet_mcp.setup._find_searx_package_dir") as mock_find_dir:
        # Case 1: SearXNG not found
        mock_find_dir.return_value = None
        patch_searxng_version() # Should not raise

        # Case 2: vf exists
        mock_dir = MagicMock(spec=Path)
        mock_vf = MagicMock(spec=Path)
        mock_dir.__truediv__.return_value = mock_vf
        mock_vf.exists.return_value = True

        mock_find_dir.return_value = mock_dir
        patch_searxng_version()
        mock_vf.write_text.assert_not_called()

        # Case 3: vf missing, write it
        mock_vf.exists.return_value = False
        patch_searxng_version()
        mock_vf.write_text.assert_called_once()
        assert 'VERSION_STRING = "0.0.0"' in mock_vf.write_text.call_args[0][0]

def test_patch_searxng_windows():
    # We need to mock sys.platform. Since it's not a function, we mock it via patch
    # But sys is imported in the module. We should patch wet_mcp.setup.sys.platform
    # However, sys is a C extension module, might be tricky.
    # Usually patch('sys.platform', 'win32') works if done correctly.

    with patch("sys.platform", "win32"):
        with patch("wet_mcp.setup._find_searx_package_dir") as mock_find_dir:
             # Case 1: Not found
            mock_find_dir.return_value = None
            patch_searxng_windows()

            # Case 2: Found, valkeydb.py exists
            mock_dir = MagicMock(spec=Path)
            mock_valkey = MagicMock(spec=Path)
            mock_dir.__truediv__.return_value = mock_valkey
            mock_valkey.exists.return_value = True

            # Content needs patching
            original_content = "import pwd\nStart\n        _pw = pwd.getpwuid(os.getuid())\n        logger.exception(\"[%s (%s)] can't connect valkey DB ...\", _pw.pw_name, _pw.pw_uid)"
            mock_valkey.read_text.return_value = original_content

            mock_find_dir.return_value = mock_dir
            patch_searxng_windows()

            mock_valkey.write_text.assert_called_once()
            new_content = mock_valkey.write_text.call_args[0][0]
            assert "try:\n    import pwd" in new_content
            assert "if pwd and hasattr(os, 'getuid'):" in new_content

def test_patch_searxng_windows_non_win32():
    with patch("sys.platform", "linux"):
        with patch("wet_mcp.setup._find_searx_package_dir") as mock_find_dir:
            patch_searxng_windows()
            mock_find_dir.assert_not_called()

# --- Installation Tests ---

def test_install_searxng_already_installed():
    # Simulate searx being importable
    # We need to patch sys.modules so 'import searx' works
    with patch.dict(sys.modules, {"searx": MagicMock()}):
        assert _install_searxng() is True

def test_install_searxng_success():
    # Simulate searx NOT being importable initially
    # We can't easily remove it from sys.modules if it's there, but we can patch it to raise ImportError?
    # No, patch.dict(sys.modules) can remove keys if we don't include them? No.
    # We can use a context manager to temporarily remove it.

    with patch.dict(sys.modules):
        if "searx" in sys.modules:
            del sys.modules["searx"]

        with patch("wet_mcp.setup.subprocess.run") as mock_run, \
             patch("wet_mcp.setup.patch_searxng_version") as mock_patch_ver, \
             patch("wet_mcp.setup.patch_searxng_windows") as mock_patch_win:

            # Mock success for both calls
            mock_process = MagicMock()
            mock_process.returncode = 0
            mock_run.return_value = mock_process

            assert _install_searxng() is True

            assert mock_run.call_count == 2
            mock_patch_ver.assert_called_once()
            mock_patch_win.assert_called_once()

def test_install_searxng_deps_fail():
    with patch.dict(sys.modules):
        if "searx" in sys.modules:
            del sys.modules["searx"]

        with patch("wet_mcp.setup.subprocess.run") as mock_run:
            # Deps install fails
            mock_process = MagicMock()
            mock_process.returncode = 1
            mock_process.stderr = "Error"
            mock_run.return_value = mock_process

            assert _install_searxng() is False
            assert mock_run.call_count == 1

def test_install_searxng_install_fail():
    with patch.dict(sys.modules):
        if "searx" in sys.modules:
            del sys.modules["searx"]

        with patch("wet_mcp.setup.subprocess.run") as mock_run:
            # Deps succeed, Install fails
            mock_process_ok = MagicMock()
            mock_process_ok.returncode = 0

            mock_process_fail = MagicMock()
            mock_process_fail.returncode = 1
            mock_process_fail.stderr = "Error"

            mock_run.side_effect = [mock_process_ok, mock_process_fail]

            assert _install_searxng() is False
            assert mock_run.call_count == 2

def test_setup_crawl4ai_success():
    # Mock crawl4ai.install
    mock_install = MagicMock()
    with patch.dict(sys.modules, {"crawl4ai": MagicMock(), "crawl4ai.install": mock_install}):
        assert _setup_crawl4ai() is True
        mock_install.post_install.assert_called_once()

def test_setup_crawl4ai_failure():
    mock_install = MagicMock()
    mock_install.post_install.side_effect = Exception("Setup failed")
    with patch.dict(sys.modules, {"crawl4ai": MagicMock(), "crawl4ai.install": mock_install}):
        assert _setup_crawl4ai() is False

# --- Main Setup Flow Tests ---

def test_run_auto_setup_already_done():
    with patch("wet_mcp.setup.needs_setup", return_value=False):
        assert run_auto_setup() is True

def test_run_auto_setup_full_success():
    with patch("wet_mcp.setup.needs_setup", return_value=True), \
         patch("wet_mcp.setup.Path.home") as mock_home, \
         patch("wet_mcp.setup._install_searxng", return_value=True) as mock_install_searx, \
         patch("wet_mcp.setup._setup_crawl4ai", return_value=True) as mock_setup_crawl, \
         patch("wet_mcp.setup.SETUP_MARKER") as mock_marker:

        mock_config_dir = MagicMock()
        mock_home.return_value.__truediv__.return_value = mock_config_dir

        assert run_auto_setup() is True

        mock_config_dir.mkdir.assert_called_with(parents=True, exist_ok=True)
        mock_install_searx.assert_called_once()
        mock_setup_crawl.assert_called_once()
        mock_marker.touch.assert_called_once()

def test_run_auto_setup_searx_fail_crawl_success():
    with patch("wet_mcp.setup.needs_setup", return_value=True), \
         patch("wet_mcp.setup.Path.home") as mock_home, \
         patch("wet_mcp.setup._install_searxng", return_value=False), \
         patch("wet_mcp.setup._setup_crawl4ai", return_value=True), \
         patch("wet_mcp.setup.SETUP_MARKER") as mock_marker:

        mock_home.return_value.__truediv__.return_value = MagicMock()

        assert run_auto_setup() is True
        mock_marker.touch.assert_called_once()

def test_run_auto_setup_crawl_fail():
    with patch("wet_mcp.setup.needs_setup", return_value=True), \
         patch("wet_mcp.setup.Path.home") as mock_home, \
         patch("wet_mcp.setup._install_searxng", return_value=True), \
         patch("wet_mcp.setup._setup_crawl4ai", return_value=False), \
         patch("wet_mcp.setup.SETUP_MARKER") as mock_marker:

        mock_home.return_value.__truediv__.return_value = MagicMock()

        assert run_auto_setup() is False
        mock_marker.touch.assert_not_called()

def test_install_searxng_timeout():
    from subprocess import TimeoutExpired
    with patch.dict(sys.modules):
        if "searx" in sys.modules:
            del sys.modules["searx"]

        with patch("wet_mcp.setup.subprocess.run") as mock_run:
            mock_run.side_effect = TimeoutExpired(cmd="pip", timeout=120)

            assert _install_searxng() is False

def test_install_searxng_arguments():
    with patch.dict(sys.modules):
        if "searx" in sys.modules:
            del sys.modules["searx"]

        with patch("wet_mcp.setup.subprocess.run") as mock_run,              patch("wet_mcp.setup.patch_searxng_version"),              patch("wet_mcp.setup.patch_searxng_windows"):

            mock_process = MagicMock()
            mock_process.returncode = 0
            mock_run.return_value = mock_process

            _install_searxng()

            # Verify first call (deps)
            args, kwargs = mock_run.call_args_list[0]
            assert args[0][0] == sys.executable
            assert "msgspec" in args[0]
            assert kwargs["capture_output"] is True

            # Verify second call (searxng)
            args, kwargs = mock_run.call_args_list[1]
            assert args[0][0] == sys.executable
            assert "--no-build-isolation" in args[0]
            assert "github.com/searxng/searxng" in args[0][-1]
