"""Tests for wet_mcp.token_store module."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from wet_mcp.token_store import (
    _get_token_dir,
    get_token_path,
    load_token,
    save_token,
)


@pytest.fixture
def token_dir(tmp_path):
    """Provide a temp token directory and patch settings."""
    d = tmp_path / "tokens"
    d.mkdir()
    with patch("wet_mcp.token_store.settings") as mock_settings:
        mock_settings.get_data_dir.return_value = tmp_path
        yield d


def test_get_token_dir(token_dir):
    """Test _get_token_dir helper."""
    assert _get_token_dir() == token_dir


def test_get_token_path(token_dir):
    """Test get_token_path returns correct provider path."""
    assert get_token_path("drive") == token_dir / "drive.json"


def test_load_missing_token(token_dir):
    """load_token returns None if file doesn't exist."""
    assert load_token("drive") is None


def test_save_and_load_token(token_dir):
    """Test standard save and load flow."""
    token = {"access_token": "abc123", "token_type": "Bearer"}
    save_token("drive", token)

    loaded = load_token("drive")
    assert loaded == token

    # Verify file exists
    path = get_token_path("drive")
    assert path.exists()


def test_load_invalid_json(token_dir):
    """load_token returns None for malformed JSON."""
    path = get_token_path("drive")
    path.write_text("not json", encoding="utf-8")
    assert load_token("drive") is None


def test_load_non_dict_json(token_dir):
    """load_token returns None if JSON is not a dictionary."""
    path = get_token_path("drive")
    path.write_text(json.dumps([1, 2, 3]), encoding="utf-8")
    assert load_token("drive") is None


def test_load_no_access_token(token_dir):
    """load_token returns None if access_token key is missing."""
    path = get_token_path("drive")
    path.write_text(json.dumps({"refresh_token": "xyz"}), encoding="utf-8")
    assert load_token("drive") is None


def test_load_oserror(token_dir):
    """load_token handles OSError during read."""
    with patch.object(Path, "exists", side_effect=OSError("disk error")):
        assert load_token("drive") is None


def test_save_token_creates_dir(tmp_path):
    """save_token creates token dir if it doesn't exist."""
    with patch("wet_mcp.token_store.settings") as mock_settings:
        mock_settings.get_data_dir.return_value = tmp_path
        save_token("s3", {"access_token": "abc"})
        assert (tmp_path / "tokens" / "s3.json").exists()


def test_save_token_chmod_oserror(token_dir):
    """save_token ignores OSError from chmod."""
    with patch.object(Path, "chmod", side_effect=OSError("perm error")):
        # Should not raise exception
        save_token("drive", {"access_token": "test"})
        assert (token_dir / "drive.json").exists()


def test_save_token_windows_permissions(token_dir):
    """On Windows, skip chmod calls."""
    with (
        patch("wet_mcp.token_store.os.name", "nt"),
        patch.object(Path, "chmod") as mock_chmod,
    ):
        save_token("drive", {"access_token": "test"})
        mock_chmod.assert_not_called()
        assert load_token("drive") == {"access_token": "test"}


def test_save_token_unix_permissions(token_dir):
    """On Unix, set 0700 for dir and 0600 for file."""
    with (
        patch("wet_mcp.token_store.os.name", "posix"),
        patch.object(Path, "chmod") as mock_chmod,
    ):
        save_token("drive", {"access_token": "test"})
        # Verify chmod was called (once for dir, once for file)
        assert mock_chmod.call_count == 2
