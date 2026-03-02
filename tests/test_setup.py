import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

from wet_mcp.setup import (
    _get_pip_command,
    _install_searxng,
    _setup_crawl4ai,
    needs_setup,
    patch_searxng_version,
    patch_searxng_windows,
    reset_setup,
    run_auto_setup,
)


@patch("wet_mcp.setup.SETUP_MARKER")
def test_needs_setup_true(mock_marker):
    mock_marker.exists.return_value = False
    assert needs_setup() is True


@patch("wet_mcp.setup.SETUP_MARKER")
def test_needs_setup_false(mock_marker):
    mock_marker.exists.return_value = True
    assert needs_setup() is False


@patch("wet_mcp.setup._install_searxng")
@patch("wet_mcp.setup._setup_crawl4ai")
@patch("pathlib.Path.mkdir")
@patch("wet_mcp.setup.SETUP_MARKER")
@patch("wet_mcp.setup.needs_setup")
def test_run_auto_setup_success(
    mock_needs, mock_marker, mock_mkdir, mock_crawl, mock_searx
):
    mock_needs.return_value = True
    mock_searx.return_value = True
    mock_crawl.return_value = True
    assert run_auto_setup() is True
    mock_mkdir.assert_called_once()
    mock_searx.assert_called_once()
    mock_crawl.assert_called_once()
    mock_marker.touch.assert_called_once()


@patch("wet_mcp.setup._install_searxng")
@patch("wet_mcp.setup._setup_crawl4ai")
@patch("pathlib.Path.mkdir")
@patch("wet_mcp.setup.SETUP_MARKER")
@patch("wet_mcp.setup.needs_setup")
def test_run_auto_setup_partial_failure(
    mock_needs, mock_marker, mock_mkdir, mock_crawl, mock_searx
):
    mock_needs.return_value = True
    mock_searx.return_value = False
    mock_crawl.return_value = True
    assert run_auto_setup() is True
    mock_mkdir.assert_called_once()
    mock_searx.assert_called_once()
    mock_crawl.assert_called_once()
    mock_marker.touch.assert_called_once()


@patch("wet_mcp.setup._install_searxng")
@patch("wet_mcp.setup._setup_crawl4ai")
@patch("pathlib.Path.mkdir")
@patch("wet_mcp.setup.SETUP_MARKER")
@patch("wet_mcp.setup.needs_setup")
def test_run_auto_setup_failure(
    mock_needs, mock_marker, mock_mkdir, mock_crawl, mock_searx
):
    mock_needs.return_value = True
    mock_searx.return_value = True
    mock_crawl.return_value = False
    assert run_auto_setup() is False
    mock_marker.touch.assert_not_called()


@patch.dict("sys.modules", {"searx": None})
@patch("wet_mcp.setup.patch_searxng_version")
@patch("wet_mcp.setup.patch_searxng_windows")
@patch("subprocess.run")
@patch("wet_mcp.setup._get_pip_command")
def test_install_searxng_success(mock_pip, mock_run, mock_patch_win, mock_patch_ver):
    mock_pip.return_value = ["pip", "install"]
    mock_run.return_value = MagicMock(returncode=0)
    assert _install_searxng() is True
    assert mock_run.call_count == 2
    mock_patch_ver.assert_called_once()
    mock_patch_win.assert_called_once()


@patch.dict("sys.modules", {"searx": None})
@patch("subprocess.run")
@patch("wet_mcp.setup._get_pip_command")
def test_install_searxng_deps_fail(mock_pip, mock_run):
    mock_pip.return_value = ["pip", "install"]
    mock_run.return_value = MagicMock(returncode=1, stderr="error")
    assert _install_searxng() is False
    assert mock_run.call_count == 1


@patch.dict("sys.modules", {"searx": MagicMock()})
def test_install_searxng_already_installed():
    assert _install_searxng() is True


@patch("subprocess.run")
def test_setup_crawl4ai_success(mock_run):
    mock_run.return_value = MagicMock(returncode=0)
    assert _setup_crawl4ai() is True
    assert mock_run.call_count == 2


@patch("subprocess.run")
def test_setup_crawl4ai_fail(mock_run):
    mock_run.side_effect = Exception("test error")
    assert _setup_crawl4ai() is False


@patch("wet_mcp.setup.SETUP_MARKER")
def test_reset_setup(mock_marker):
    mock_marker.exists.return_value = True
    reset_setup()
    mock_marker.unlink.assert_called_once()


@patch("wet_mcp.setup.SETUP_MARKER")
def test_reset_setup_no_marker(mock_marker):
    mock_marker.exists.return_value = False
    reset_setup()
    mock_marker.unlink.assert_not_called()


@patch("shutil.which")
@patch("sys.executable", "python3")
def test_get_pip_command_uv(mock_which):
    mock_which.side_effect = lambda x: "uv" if x == "uv" else None
    assert _get_pip_command() == ["uv", "pip", "install", "--python", "python3"]


@patch("shutil.which")
@patch("sys.executable", "python3")
def test_get_pip_command_pip(mock_which):
    mock_which.side_effect = lambda x: "pip" if x == "pip" else None
    assert _get_pip_command() == ["pip", "install"]


@patch("shutil.which")
@patch("sys.executable", "python3")
def test_get_pip_command_fallback(mock_which):
    mock_which.return_value = None
    assert _get_pip_command() == ["python3", "-m", "pip", "install"]


@patch("wet_mcp.setup._find_searx_package_dir")
def test_patch_searxng_version_success(mock_find):
    mock_dir = MagicMock(spec=Path)
    mock_find.return_value = mock_dir
    mock_file = MagicMock(spec=Path)
    mock_dir.__truediv__.return_value = mock_file
    mock_file.exists.return_value = False
    patch_searxng_version()
    mock_file.write_text.assert_called_once()


@patch("wet_mcp.setup._find_searx_package_dir")
def test_patch_searxng_version_exists(mock_find):
    mock_dir = MagicMock(spec=Path)
    mock_find.return_value = mock_dir
    mock_file = MagicMock(spec=Path)
    mock_dir.__truediv__.return_value = mock_file
    mock_file.exists.return_value = True
    patch_searxng_version()
    mock_file.write_text.assert_not_called()


@patch("sys.platform", "win32")
@patch("wet_mcp.setup._find_searx_package_dir")
def test_patch_searxng_windows_success(mock_find):
    mock_dir = MagicMock(spec=Path)
    mock_find.return_value = mock_dir
    mock_file = MagicMock(spec=Path)
    mock_dir.__truediv__.return_value = mock_file
    mock_file.exists.return_value = True
    mock_file.read_text.return_value = "import pwd\n"
    patch_searxng_windows()
    mock_file.write_text.assert_called_once()


@patch("sys.platform", "win32")
@patch("wet_mcp.setup._find_searx_package_dir")
def test_patch_searxng_windows_already_patched(mock_find):
    mock_dir = MagicMock(spec=Path)
    mock_find.return_value = mock_dir
    mock_file = MagicMock(spec=Path)
    mock_dir.__truediv__.return_value = mock_file
    mock_file.exists.return_value = True
    mock_file.read_text.return_value = (
        "try:\n    import pwd\nexcept ImportError:\n    pwd = None\n"
    )
    patch_searxng_windows()
    mock_file.write_text.assert_not_called()


@patch("sys.platform", "win32")
@patch("wet_mcp.setup._find_searx_package_dir")
def test_patch_searxng_windows_no_pwd(mock_find):
    mock_dir = MagicMock(spec=Path)
    mock_find.return_value = mock_dir
    mock_file = MagicMock(spec=Path)
    mock_dir.__truediv__.return_value = mock_file
    mock_file.exists.return_value = True
    mock_file.read_text.return_value = "import sys\n"
    patch_searxng_windows()
    mock_file.write_text.assert_not_called()


@patch("sys.platform", "linux")
@patch("wet_mcp.setup._find_searx_package_dir")
def test_patch_searxng_windows_linux(mock_find):
    patch_searxng_windows()
    mock_find.assert_not_called()


@patch("wet_mcp.setup.needs_setup", return_value=False)
def test_run_auto_setup_skip(mock_needs):
    assert run_auto_setup() is True


@patch("importlib.util.find_spec")
def test_find_searx_package_dir_found(mock_find_spec):
    from wet_mcp.setup import _find_searx_package_dir

    mock_spec = MagicMock()
    mock_spec.submodule_search_locations = ["/test/dir"]
    mock_find_spec.return_value = mock_spec
    assert _find_searx_package_dir() == Path("/test/dir")


@patch("importlib.util.find_spec", return_value=None)
def test_find_searx_package_dir_not_found(mock_find_spec):
    from wet_mcp.setup import _find_searx_package_dir

    assert _find_searx_package_dir() is None


@patch.dict("sys.modules", {"searx": None})
@patch("subprocess.run")
@patch("wet_mcp.setup._get_pip_command")
def test_install_searxng_main_fail(mock_pip, mock_run):
    mock_pip.return_value = ["pip", "install"]
    mock_run.side_effect = [MagicMock(returncode=0), MagicMock(returncode=1)]
    assert _install_searxng() is False


@patch.dict("sys.modules", {"searx": None})
@patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="pip", timeout=120))
@patch("wet_mcp.setup._get_pip_command")
def test_install_searxng_timeout(mock_pip, mock_run):
    mock_pip.return_value = ["pip", "install"]
    assert _install_searxng() is False


@patch("wet_mcp.setup._find_searx_package_dir")
def test_patch_searxng_version_exception(mock_find):
    mock_find.side_effect = Exception("test error")
    patch_searxng_version()


@patch("sys.platform", "win32")
@patch("wet_mcp.setup._find_searx_package_dir")
def test_patch_searxng_windows_exception(mock_find):
    mock_find.side_effect = Exception("test error")
    patch_searxng_windows()


@patch("importlib.util.find_spec")
def test_find_searx_package_dir_exception(mock_find_spec):
    from wet_mcp.setup import _find_searx_package_dir

    mock_find_spec.side_effect = Exception("test error")
    assert _find_searx_package_dir() is None


@patch.dict("sys.modules", {"searx": None})
@patch("wet_mcp.setup._get_pip_command")
def test_install_searxng_exception(mock_pip):
    mock_pip.side_effect = Exception("test error")
    assert _install_searxng() is False


@patch("sys.platform", "win32")
@patch("wet_mcp.setup._find_searx_package_dir")
def test_patch_searxng_windows_no_dir(mock_find):
    mock_find.return_value = None
    patch_searxng_windows()


@patch("sys.platform", "win32")
@patch("wet_mcp.setup._find_searx_package_dir")
def test_patch_searxng_windows_no_file(mock_find):
    mock_dir = MagicMock(spec=Path)
    mock_find.return_value = mock_dir
    mock_file = MagicMock(spec=Path)
    mock_dir.__truediv__.return_value = mock_file
    mock_file.exists.return_value = False
    patch_searxng_windows()


@patch("wet_mcp.setup._find_searx_package_dir")
def test_patch_searxng_version_no_dir(mock_find):
    mock_find.return_value = None
    patch_searxng_version()
