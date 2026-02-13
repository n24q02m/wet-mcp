import sys
from unittest.mock import MagicMock, patch

# We import from wet_mcp.setup, but these names might not exist yet if running before refactor.
# However, we are creating the test file now.
from wet_mcp.setup import (
    get_pip_command,
    install_searxng,
    is_searxng_installed,
)


class TestGetPipCommand:
    @patch("shutil.which")
    def test_uv_found(self, mock_which):
        """Should prefer uv pip if uv is available."""
        mock_which.side_effect = lambda cmd: "/usr/bin/uv" if cmd == "uv" else None
        cmd = get_pip_command()
        assert cmd == ["/usr/bin/uv", "pip", "install"]

    @patch("shutil.which")
    def test_pip_found_no_uv(self, mock_which):
        """Should use pip if uv is missing but pip is found."""
        mock_which.side_effect = lambda cmd: "/usr/bin/pip" if cmd == "pip" else None
        cmd = get_pip_command()
        assert cmd == ["/usr/bin/pip", "install"]

    @patch("shutil.which")
    def test_fallback_python_m_pip(self, mock_which):
        """Should fallback to python -m pip if neither uv nor pip is found."""
        mock_which.return_value = None
        cmd = get_pip_command()
        assert cmd == [sys.executable, "-m", "pip", "install"]


class TestIsSearxngInstalled:
    def test_installed(self):
        """Should return True if searx can be imported."""
        with patch.dict(sys.modules, {"searx": MagicMock()}):
            assert is_searxng_installed() is True


class TestInstallSearxng:
    @patch("wet_mcp.setup.is_searxng_installed")
    @patch("wet_mcp.setup.get_pip_command")
    @patch("subprocess.run")
    @patch("wet_mcp.setup.patch_searxng_version")
    @patch("wet_mcp.setup.patch_searxng_windows")
    def test_already_installed(
        self,
        mock_patch_windows,
        mock_patch_version,
        mock_run,
        mock_get_pip,
        mock_is_installed,
    ):
        """Should return True immediately if already installed."""
        mock_is_installed.return_value = True

        assert install_searxng() is True

        mock_run.assert_not_called()

    @patch("wet_mcp.setup.is_searxng_installed")
    @patch("wet_mcp.setup.get_pip_command")
    @patch("subprocess.run")
    @patch("wet_mcp.setup.patch_searxng_version")
    @patch("wet_mcp.setup.patch_searxng_windows")
    def test_install_success(
        self,
        mock_patch_windows,
        mock_patch_version,
        mock_run,
        mock_get_pip,
        mock_is_installed,
    ):
        """Should run pip install and patch functions on success."""
        mock_is_installed.return_value = False
        mock_get_pip.return_value = ["pip", "install"]

        # Mock subprocess.run for deps and install
        mock_run.side_effect = [
            MagicMock(returncode=0),  # deps
            MagicMock(returncode=0),  # install
        ]

        assert install_searxng() is True

        assert mock_run.call_count == 2
        mock_patch_version.assert_called_once()
        mock_patch_windows.assert_called_once()

    @patch("wet_mcp.setup.is_searxng_installed")
    @patch("wet_mcp.setup.get_pip_command")
    @patch("subprocess.run")
    def test_install_failure(
        self,
        mock_run,
        mock_get_pip,
        mock_is_installed,
    ):
        """Should return False if pip install fails."""
        mock_is_installed.return_value = False
        mock_get_pip.return_value = ["pip", "install"]

        # Mock subprocess.run for deps success, install failure
        mock_run.side_effect = [
            MagicMock(returncode=0),  # deps
            MagicMock(returncode=1, stderr="Error"),  # install
        ]

        assert install_searxng() is False
