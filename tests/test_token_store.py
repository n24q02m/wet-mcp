"""Tests for wet_mcp.token_store module."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from wet_mcp.token_store import (
    delete_token,
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


def test_delete_existing(token_dir):
    with patch("wet_mcp.token_store.settings") as mock_settings:
        mock_settings.get_data_dir.return_value = token_dir.parent
        save_token("drive", {"access_token": "test"})
        assert delete_token("drive") is True
        assert not get_token_path("drive").exists()


def test_delete_nonexistent(token_dir):
    with patch("wet_mcp.token_store.settings") as mock_settings:
        mock_settings.get_data_dir.return_value = token_dir.parent
        assert delete_token("drive") is False


def test_save_token_creates_dir(tmp_path):
    """save_token creates token dir if it doesn't exist."""
    with patch("wet_mcp.token_store.settings") as mock_settings:
        mock_settings.get_data_dir.return_value = tmp_path
        save_token("s3", {"access_token": "abc"})
        assert (tmp_path / "tokens" / "s3.json").exists()


def test_save_token_windows_permissions(token_dir):
    """On Windows, skip chmod calls."""
    with (
        patch("wet_mcp.token_store.settings") as mock_settings,
        patch("wet_mcp.token_store.os.name", "nt"),
    ):
        mock_settings.get_data_dir.return_value = token_dir.parent
        save_token("drive", {"access_token": "test"})
        assert load_token("drive") == {"access_token": "test"}


def test_delete_token_oserror(token_dir):
    """delete_token returns False if unlink fails with OSError."""
    with patch("wet_mcp.token_store.settings") as mock_settings:
        mock_settings.get_data_dir.return_value = token_dir.parent
        save_token("drive", {"access_token": "test"})
        with patch.object(Path, "unlink", side_effect=OSError("permission denied")):
            assert delete_token("drive") is False


def test_save_token_chmod_error(token_dir):
    """save_token catches OSError from chmod."""
    with (
        patch("wet_mcp.token_store.settings") as mock_settings,
        patch.object(Path, "chmod", side_effect=OSError("permission denied")),
    ):
        mock_settings.get_data_dir.return_value = token_dir.parent
        # Should not raise
        save_token("drive", {"access_token": "test"})
        assert load_token("drive") == {"access_token": "test"}
