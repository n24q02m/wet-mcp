"""Tests for wet_mcp.token_store module."""

import json
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from wet_mcp.token_store import (
    _set_secure_permissions,
    get_token_path,
    load_token,
    save_token,
)


@pytest.fixture
def mock_settings(tmp_path):
    """Mock settings with a temp data directory."""
    with patch("wet_mcp.token_store.settings") as m:
        m.get_config_dir.return_value = tmp_path
        m.get_data_dir.return_value = tmp_path
        yield m


def test_get_token_path(mock_settings, tmp_path):
    path = get_token_path("drive")
    assert path == tmp_path / "drive_token.json"


def test_load_missing_token(mock_settings):
    assert load_token("drive") is None


def test_save_and_load_token(mock_settings, tmp_path):
    token = {"access_token": "abc123", "token_type": "Bearer"}
    save_token("drive", token)

    loaded = load_token("drive")
    assert loaded == token

    path = get_token_path("drive")
    assert path.exists()


def test_load_invalid_json(mock_settings, tmp_path):
    path = get_token_path("drive")
    path.write_text("not json", encoding="utf-8")
    assert load_token("drive") is None


def test_load_no_access_token(mock_settings, tmp_path):
    path = get_token_path("drive")
    path.write_text(json.dumps({"refresh_token": "xyz"}), encoding="utf-8")
    assert load_token("drive") is None


def test_load_oserror(mock_settings):
    with patch.object(Path, "exists", side_effect=OSError("disk error")):
        assert load_token("drive") is None


def test_save_token_creates_dir(mock_settings, tmp_path):
    save_token("s3", {"access_token": "abc"})
    assert (tmp_path / "s3_token.json").exists()


@patch("os.name", "posix")
def test_set_secure_permissions_unix(tmp_path):
    file_path = tmp_path / "test_file"
    file_path.touch()
    dir_path = tmp_path / "test_dir"
    dir_path.mkdir()

    with patch.object(Path, "chmod") as mock_chmod:
        _set_secure_permissions(file_path, is_dir=False)
        # 0600 = 384
        mock_chmod.assert_called_with(0o600)

        _set_secure_permissions(dir_path, is_dir=True)
        # 0700 = 448
        mock_chmod.assert_called_with(0o700)


@patch("os.name", "posix")
def test_set_secure_permissions_unix_error(tmp_path):
    file_path = tmp_path / "test_file"
    file_path.touch()
    with patch.object(Path, "chmod", side_effect=OSError("perm error")):
        # Should not raise
        _set_secure_permissions(file_path)


@patch("os.name", "nt")
@patch("getpass.getuser", return_value="testuser")
@patch("subprocess.run")
def test_set_secure_permissions_windows(mock_run, mock_getuser, tmp_path):
    path = tmp_path / "test_file"
    path.touch()

    _set_secure_permissions(path)

    assert mock_run.call_count == 2
    mock_run.assert_any_call(
        ["icacls", str(path), "/inheritance:r"],
        check=True,
        capture_output=True,
    )
    mock_run.assert_any_call(
        ["icacls", str(path), "/grant:r", "testuser:F"],
        check=True,
        capture_output=True,
    )


@patch("os.name", "nt")
@patch("subprocess.run", side_effect=subprocess.CalledProcessError(1, "cmd"))
def test_set_secure_permissions_windows_error(mock_run, tmp_path):
    path = tmp_path / "test_file"
    path.touch()
    # Should not raise
    _set_secure_permissions(path)
