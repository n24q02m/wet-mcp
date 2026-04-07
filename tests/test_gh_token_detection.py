import subprocess
from unittest.mock import patch, MagicMock
from wet_mcp.server import _detect_gh_token

def test_detect_gh_token_success():
    with patch("shutil.which", return_value="/usr/bin/gh"):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="gh_token_123\n")
            assert _detect_gh_token() == "gh_token_123"

def test_detect_gh_token_no_gh_cli():
    with patch("shutil.which", return_value=None):
        assert _detect_gh_token() is None

def test_detect_gh_token_not_authenticated():
    with patch("shutil.which", return_value="/usr/bin/gh"):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stdout="")
            assert _detect_gh_token() is None

def test_detect_gh_token_timeout():
    with patch("shutil.which", return_value="/usr/bin/gh"):
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd=["gh"], timeout=5)):
            assert _detect_gh_token() is None

def test_detect_gh_token_os_error():
    with patch("shutil.which", return_value="/usr/bin/gh"):
        with patch("subprocess.run", side_effect=OSError("Failed to execute")):
            assert _detect_gh_token() is None
