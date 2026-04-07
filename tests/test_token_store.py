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
def token_dir(tmp_path):
    """Provide a temp token directory."""
    d = tmp_path / "tokens"
    d.mkdir()
    with patch("wet_mcp.token_store.settings") as mock_settings:
        mock_settings.get_data_dir.return_value = tmp_path
        yield d


def test_get_token_path(token_dir):
    with patch("wet_mcp.token_store.settings") as mock_settings:
        mock_settings.get_data_dir.return_value = token_dir.parent
        path = get_token_path("drive")
        assert path == token_dir / "drive.json"


def test_load_missing_token(token_dir):
    with patch("wet_mcp.token_store.settings") as mock_settings:
        mock_settings.get_data_dir.return_value = token_dir.parent
        assert load_token("drive") is None


def test_save_and_load_token(token_dir):
    with patch("wet_mcp.token_store.settings") as mock_settings:
        mock_settings.get_data_dir.return_value = token_dir.parent
        token = {"access_token": "abc123", "token_type": "Bearer"}
        save_token("drive", token)

        loaded = load_token("drive")
        assert loaded == token

        # Verify file permissions on Unix
        path = get_token_path("drive")
        assert path.exists()


def test_load_invalid_json(token_dir):
    with patch("wet_mcp.token_store.settings") as mock_settings:
        mock_settings.get_data_dir.return_value = token_dir.parent
        path = get_token_path("drive")
        path.write_text("not json", encoding="utf-8")
        assert load_token("drive") is None


def test_load_no_access_token(token_dir):
    with patch("wet_mcp.token_store.settings") as mock_settings:
        mock_settings.get_data_dir.return_value = token_dir.parent
        path = get_token_path("drive")
        path.write_text(json.dumps({"refresh_token": "xyz"}), encoding="utf-8")
        assert load_token("drive") is None


def test_load_oserror(token_dir):
    with patch("wet_mcp.token_store.settings") as mock_settings:
        mock_settings.get_data_dir.return_value = token_dir.parent
        with patch.object(Path, "exists", side_effect=OSError("disk error")):
            assert load_token("drive") is None


def test_save_token_creates_dir(tmp_path):
    """save_token creates token dir if it doesn't exist."""
    with patch("wet_mcp.token_store.settings") as mock_settings:
        mock_settings.get_data_dir.return_value = tmp_path
        save_token("s3", {"access_token": "abc"})
        assert (tmp_path / "tokens" / "s3.json").exists()


def test_save_token_windows_permissions(token_dir):
    """On Windows, use icacls via subprocess."""
    with (
        patch("wet_mcp.token_store.settings") as mock_settings,
        patch("wet_mcp.token_store.os.name", "nt"),
        patch("wet_mcp.token_store.getpass.getuser", return_value="testuser"),
        patch("wet_mcp.token_store.subprocess.run") as mock_run,
    ):
        mock_settings.get_data_dir.return_value = token_dir.parent
        save_token("drive", {"access_token": "test"})
        assert load_token("drive") == {"access_token": "test"}
        # Called twice: once for dir, once for file
        assert mock_run.call_count == 2
        args, _ = mock_run.call_args_list[0]
        assert "icacls" in args[0]
        assert "testuser:F" in args[0]


def test_set_secure_permissions_unix(tmp_path):
    """Test Unix permission setting."""
    path = tmp_path / "test_file"
    path.touch()

    with patch("os.name", "posix"), patch.object(Path, "chmod") as mock_chmod:
        _set_secure_permissions(path, is_dir=False)
        mock_chmod.assert_called_once_with(0o600)

    dir_path = tmp_path / "test_dir"
    dir_path.mkdir()
    with patch("os.name", "posix"), patch.object(Path, "chmod") as mock_chmod:
        _set_secure_permissions(dir_path, is_dir=True)
        mock_chmod.assert_called_once_with(0o700)


def test_set_secure_permissions_windows_failure(tmp_path):
    """Test Windows permission setting failure handles exceptions."""
    path = tmp_path / "test_file"
    path.touch()

    with (
        patch("wet_mcp.token_store.os.name", "nt"),
        patch("wet_mcp.token_store.getpass.getuser", return_value="testuser"),
        patch(
            "wet_mcp.token_store.subprocess.run",
            side_effect=subprocess.CalledProcessError(1, "icacls"),
        ),
        patch("wet_mcp.token_store.logger") as mock_logger,
    ):
        # Should not raise
        _set_secure_permissions(path)
        mock_logger.warning.assert_called_once()
