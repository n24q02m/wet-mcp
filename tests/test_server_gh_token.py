import subprocess
from unittest.mock import patch, MagicMock
from wet_mcp.server import _detect_gh_token

def test_detect_gh_token_success():
    with patch("shutil.which", return_value="/usr/bin/gh"):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="my-token\n")
            assert _detect_gh_token() == "my-token"

def test_detect_gh_token_no_gh():
    with patch("shutil.which", return_value=None):
        assert _detect_gh_token() is None

def test_detect_gh_token_timeout():
    with patch("shutil.which", return_value="/usr/bin/gh"):
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd=["gh"], timeout=5)):
            assert _detect_gh_token() is None

def test_detect_gh_token_os_error():
    with patch("shutil.which", return_value="/usr/bin/gh"):
        with patch("subprocess.run", side_effect=OSError("binary not executable")):
            assert _detect_gh_token() is None
