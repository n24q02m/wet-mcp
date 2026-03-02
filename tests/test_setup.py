import subprocess
import sys
import unittest.mock
from pathlib import Path
from unittest.mock import MagicMock, patch

# Mock dependencies before importing anything from wet_mcp to avoid import errors in testing isolation
sys.modules["crawl4ai"] = unittest.mock.MagicMock()
sys.modules["litellm"] = unittest.mock.MagicMock()
sys.modules["sqlite_vec"] = unittest.mock.MagicMock()
# sys.modules["numpy"] = unittest.mock.MagicMock()


# Note: We must mock setup.SETUP_MARKER during tests to avoid filesystem interaction
from wet_mcp.setup import (  # noqa: E402
    _find_searx_package_dir,
    _get_pip_command,
    _install_searxng,
    _setup_crawl4ai,
    needs_setup,
    patch_searxng_version,
    patch_searxng_windows,
    reset_setup,
    run_auto_setup,
)

# --- _find_searx_package_dir ---


@patch("importlib.util.find_spec")
def test_find_searx_package_dir_found(mock_find_spec):
    mock_spec = MagicMock()
    mock_spec.submodule_search_locations = ["/path/to/searx"]
    mock_find_spec.return_value = mock_spec

    result = _find_searx_package_dir()
    assert result == Path("/path/to/searx")


@patch("importlib.util.find_spec")
def test_find_searx_package_dir_not_found(mock_find_spec):
    mock_spec = MagicMock()
    mock_spec.submodule_search_locations = None
    mock_find_spec.return_value = mock_spec

    assert _find_searx_package_dir() is None

    mock_find_spec.return_value = None
    assert _find_searx_package_dir() is None


@patch("importlib.util.find_spec", side_effect=Exception("Test Error"))
def test_find_searx_package_dir_exception(mock_find_spec):
    assert _find_searx_package_dir() is None


# --- patch_searxng_version ---


@patch("wet_mcp.setup._find_searx_package_dir")
def test_patch_searxng_version_no_dir(mock_find_dir):
    mock_find_dir.return_value = None
    # Should not raise any error
    patch_searxng_version()


@patch("wet_mcp.setup._find_searx_package_dir")
def test_patch_searxng_version_exists(mock_find_dir):
    mock_dir = MagicMock(spec=Path)
    mock_find_dir.return_value = mock_dir
    mock_file = MagicMock(spec=Path)
    mock_dir.__truediv__.return_value = mock_file
    mock_file.exists.return_value = True

    patch_searxng_version()
    mock_file.write_text.assert_not_called()


@patch("wet_mcp.setup._find_searx_package_dir")
def test_patch_searxng_version_not_exists(mock_find_dir):
    mock_dir = MagicMock(spec=Path)
    mock_find_dir.return_value = mock_dir
    mock_file = MagicMock(spec=Path)
    mock_dir.__truediv__.return_value = mock_file
    mock_file.exists.return_value = False

    patch_searxng_version()
    mock_file.write_text.assert_called_once()
    content = mock_file.write_text.call_args[0][0]
    assert 'VERSION_STRING = "0.0.0"' in content


@patch("wet_mcp.setup._find_searx_package_dir", side_effect=Exception("Test Exception"))
def test_patch_searxng_version_exception(mock_find_dir):
    patch_searxng_version()


# --- patch_searxng_windows ---


def test_patch_searxng_windows_not_win32():
    with patch("sys.platform", "linux"):
        patch_searxng_windows()


def test_patch_searxng_windows_no_dir():
    with (
        patch("sys.platform", "win32"),
        patch("wet_mcp.setup._find_searx_package_dir", return_value=None),
    ):
        patch_searxng_windows()


def test_patch_searxng_windows_no_valkeydb():
    mock_dir = MagicMock(spec=Path)
    mock_file = MagicMock(spec=Path)
    mock_dir.__truediv__.return_value = mock_file
    mock_file.exists.return_value = False

    with (
        patch("sys.platform", "win32"),
        patch("wet_mcp.setup._find_searx_package_dir", return_value=mock_dir),
    ):
        patch_searxng_windows()
        mock_file.read_text.assert_not_called()


def test_patch_searxng_windows_already_patched():
    mock_dir = MagicMock(spec=Path)
    mock_file = MagicMock(spec=Path)
    mock_dir.__truediv__.return_value = mock_file
    mock_file.exists.return_value = True

    # Already patched content
    mock_file.read_text.return_value = "except ImportError\npwd = None"

    with (
        patch("sys.platform", "win32"),
        patch("wet_mcp.setup._find_searx_package_dir", return_value=mock_dir),
    ):
        patch_searxng_windows()
        mock_file.write_text.assert_not_called()


def test_patch_searxng_windows_no_pwd():
    mock_dir = MagicMock(spec=Path)
    mock_file = MagicMock(spec=Path)
    mock_dir.__truediv__.return_value = mock_file
    mock_file.exists.return_value = True

    # Missing import pwd
    mock_file.read_text.return_value = "def nothing(): pass"

    with (
        patch("sys.platform", "win32"),
        patch("wet_mcp.setup._find_searx_package_dir", return_value=mock_dir),
    ):
        patch_searxng_windows()
        mock_file.write_text.assert_not_called()


def test_patch_searxng_windows_needs_patch():
    mock_dir = MagicMock(spec=Path)
    mock_file = MagicMock(spec=Path)
    mock_dir.__truediv__.return_value = mock_file
    mock_file.exists.return_value = True

    original_content = (
        "import pwd\n"
        "        _pw = pwd.getpwuid(os.getuid())\n"
        '        logger.exception("[%s (%s)] can\'t connect valkey DB ...", _pw.pw_name, _pw.pw_uid)'
    )
    mock_file.read_text.return_value = original_content

    with (
        patch("sys.platform", "win32"),
        patch("wet_mcp.setup._find_searx_package_dir", return_value=mock_dir),
    ):
        patch_searxng_windows()
        mock_file.write_text.assert_called_once()
        written = mock_file.write_text.call_args[0][0]
        assert "try:\n    import pwd\nexcept ImportError:\n    pwd = None\n" in written
        assert "if pwd and hasattr(os, 'getuid'):" in written


def test_patch_searxng_windows_exception():
    with (
        patch("sys.platform", "win32"),
        patch("wet_mcp.setup._find_searx_package_dir", side_effect=Exception("Test")),
    ):
        patch_searxng_windows()


# --- needs_setup ---


@patch("wet_mcp.setup.SETUP_MARKER")
def test_needs_setup_true(mock_marker):
    mock_marker.exists.return_value = False
    assert needs_setup() is True


@patch("wet_mcp.setup.SETUP_MARKER")
def test_needs_setup_false(mock_marker):
    mock_marker.exists.return_value = True
    assert needs_setup() is False


# --- _get_pip_command ---


@patch("shutil.which")
def test_get_pip_command_uv(mock_which):
    def side_effect(cmd):
        if cmd == "uv":
            return "/path/to/uv"
        return None

    mock_which.side_effect = side_effect

    with patch("sys.executable", "/usr/bin/python"):
        cmd = _get_pip_command()
        assert cmd == ["/path/to/uv", "pip", "install", "--python", "/usr/bin/python"]


@patch("shutil.which")
def test_get_pip_command_pip(mock_which):
    def side_effect(cmd):
        if cmd == "pip":
            return "/path/to/pip"
        return None

    mock_which.side_effect = side_effect

    cmd = _get_pip_command()
    assert cmd == ["/path/to/pip", "install"]


@patch("shutil.which", return_value=None)
def test_get_pip_command_sys(mock_which):
    with patch("sys.executable", "/usr/bin/python"):
        cmd = _get_pip_command()
        assert cmd == ["/usr/bin/python", "-m", "pip", "install"]


# --- _install_searxng ---


@patch.dict("sys.modules", {"searx": MagicMock()})
def test_install_searxng_already_installed():
    assert _install_searxng() is True


@patch.dict("sys.modules", {"searx": None})
@patch("wet_mcp.setup._get_pip_command", return_value=["pip", "install"])
@patch("subprocess.run")
@patch("wet_mcp.setup.patch_searxng_version")
@patch("wet_mcp.setup.patch_searxng_windows")
def test_install_searxng_success(mock_win, mock_ver, mock_run, mock_get_pip):
    mock_run.return_value = MagicMock(returncode=0)
    assert _install_searxng() is True
    assert mock_run.call_count == 2
    mock_ver.assert_called_once()
    mock_win.assert_called_once()


@patch.dict("sys.modules", {"searx": None})
@patch("wet_mcp.setup._get_pip_command", return_value=["pip", "install"])
@patch("subprocess.run")
def test_install_searxng_deps_fail(mock_run, mock_get_pip):
    mock_run.return_value = MagicMock(returncode=1, stderr="deps fail")
    assert _install_searxng() is False
    assert mock_run.call_count == 1


@patch.dict("sys.modules", {"searx": None})
@patch("wet_mcp.setup._get_pip_command", return_value=["pip", "install"])
@patch("subprocess.run")
def test_install_searxng_main_fail(mock_run, mock_get_pip):
    mock_run.side_effect = [
        MagicMock(returncode=0),
        MagicMock(returncode=1, stderr="main fail"),
    ]
    assert _install_searxng() is False
    assert mock_run.call_count == 2


@patch.dict("sys.modules", {"searx": None})
@patch("wet_mcp.setup._get_pip_command", return_value=["pip", "install"])
@patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="pip", timeout=120))
def test_install_searxng_timeout(mock_run, mock_get_pip):
    assert _install_searxng() is False


@patch.dict("sys.modules", {"searx": None})
@patch("wet_mcp.setup._get_pip_command", side_effect=Exception("Test"))
def test_install_searxng_exception(mock_get_pip):
    assert _install_searxng() is False


# --- _setup_crawl4ai ---


@patch("subprocess.run")
def test_setup_crawl4ai_success(mock_run):
    mock_run.return_value = MagicMock(returncode=0)
    assert _setup_crawl4ai() is True
    assert mock_run.call_count == 2


@patch("subprocess.run", side_effect=Exception("Test"))
def test_setup_crawl4ai_exception(mock_run):
    assert _setup_crawl4ai() is False


# --- run_auto_setup ---


@patch("wet_mcp.setup.needs_setup", return_value=False)
def test_run_auto_setup_not_needed(mock_needs):
    assert run_auto_setup() is True


@patch("wet_mcp.setup.needs_setup", return_value=True)
@patch("pathlib.Path.home")
@patch("wet_mcp.setup._install_searxng", return_value=True)
@patch("wet_mcp.setup._setup_crawl4ai", return_value=True)
@patch("wet_mcp.setup.SETUP_MARKER")
def test_run_auto_setup_success(
    mock_marker, mock_crawl, mock_searx, mock_home, mock_needs
):
    mock_dir = MagicMock(spec=Path)
    mock_home.return_value = mock_dir

    mock_config = MagicMock(spec=Path)
    mock_dir.__truediv__.return_value = mock_config

    assert run_auto_setup() is True
    mock_config.mkdir.assert_called_once_with(parents=True, exist_ok=True)
    mock_searx.assert_called_once()
    mock_crawl.assert_called_once()
    mock_marker.touch.assert_called_once()


@patch("wet_mcp.setup.needs_setup", return_value=True)
@patch("pathlib.Path.home", return_value=MagicMock())
@patch("wet_mcp.setup._install_searxng", return_value=False)
@patch("wet_mcp.setup._setup_crawl4ai", return_value=True)
@patch("wet_mcp.setup.SETUP_MARKER")
def test_run_auto_setup_searxng_fail(
    mock_marker, mock_crawl, mock_searx, mock_home, mock_needs
):
    # setup continues if searxng fails
    assert run_auto_setup() is True
    mock_marker.touch.assert_called_once()


@patch("wet_mcp.setup.needs_setup", return_value=True)
@patch("pathlib.Path.home", return_value=MagicMock())
@patch("wet_mcp.setup._install_searxng", return_value=True)
@patch("wet_mcp.setup._setup_crawl4ai", return_value=False)
@patch("wet_mcp.setup.SETUP_MARKER")
def test_run_auto_setup_crawl4ai_fail(
    mock_marker, mock_crawl, mock_searx, mock_home, mock_needs
):
    assert run_auto_setup() is False
    mock_marker.touch.assert_not_called()


# --- reset_setup ---


@patch("wet_mcp.setup.SETUP_MARKER")
def test_reset_setup_exists(mock_marker):
    mock_marker.exists.return_value = True
    reset_setup()
    mock_marker.unlink.assert_called_once()


@patch("wet_mcp.setup.SETUP_MARKER")
def test_reset_setup_not_exists(mock_marker):
    mock_marker.exists.return_value = False
    reset_setup()
    mock_marker.unlink.assert_not_called()
