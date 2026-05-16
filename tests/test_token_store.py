"""Tests for wet_mcp.token_store module."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from wet_mcp.token_store import (
    _get_token_dir,
    _get_token_dir_for_sub,
    get_token_path,
    get_token_path_for_sub,
    load_token,
    load_token_for_sub,
    read_token_for_sub,
    save_token,
    save_token_for_sub,
)


@pytest.fixture
def token_dir(tmp_path):
    """Provide a temp token directory and patch settings.

    Also patches subprocess.run so the real Windows icacls call cannot
    lock down pytest tmp paths during test runs (would break cleanup).
    """
    d = tmp_path / "tokens"
    d.mkdir()
    with (
        patch("wet_mcp.token_store.settings") as mock_settings,
        patch("wet_mcp.token_store.subprocess.run"),
    ):
        mock_settings.get_data_dir.return_value = tmp_path
        yield d


def test_get_token_dir(token_dir):
    """Test _get_token_dir helper."""
    assert _get_token_dir() == token_dir


def test_get_token_path(token_dir):
    """Test get_token_path returns correct provider path."""
    assert get_token_path("drive") == token_dir / "drive.json"


def test_path_traversal_validation(token_dir):
    """Test that path traversal sequences are blocked."""
    with pytest.raises(ValueError, match="Invalid path component"):
        get_token_path("../drive")

    with pytest.raises(ValueError, match="Invalid path component"):
        get_token_path("drive/something")

    with pytest.raises(ValueError, match="Invalid path component"):
        get_token_path_for_sub("../user", "drive")

    with pytest.raises(ValueError, match="Invalid path component"):
        get_token_path_for_sub("user", "../drive")

    with pytest.raises(ValueError, match="Name cannot be empty"):
        get_token_path("")


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
    with (
        patch("wet_mcp.token_store.settings") as mock_settings,
        patch("wet_mcp.token_store.subprocess.run"),
    ):
        mock_settings.get_data_dir.return_value = tmp_path
        save_token("s3", {"access_token": "abc"})
        assert (tmp_path / "tokens" / "s3.json").exists()


def test_save_token_chmod_oserror(token_dir):
    """save_token ignores OSError from chmod (Unix branch)."""
    with (
        patch("wet_mcp.token_store.os.name", "posix"),
        patch.object(Path, "chmod", side_effect=OSError("perm error")),
    ):
        # Should not raise exception
        save_token("drive", {"access_token": "test"})
        assert (token_dir / "drive.json").exists()


def test_save_token_windows_permissions(token_dir, monkeypatch):
    """On Windows, invoke icacls (not chmod) to lock down inheritance + grant.

    Principal is DOMAIN\\user (fully qualified) so icacls does not collide with
    the machine account when username matches hostname.
    """
    monkeypatch.setenv("USERDOMAIN", "TESTDOM")
    with (
        patch("wet_mcp.token_store.os.name", "nt"),
        patch("wet_mcp.token_store.subprocess.run") as mock_run,
        patch("wet_mcp.token_store.getpass.getuser", return_value="tester"),
        patch.object(Path, "chmod") as mock_chmod,
    ):
        mock_run.return_value.returncode = 0
        save_token("drive", {"access_token": "test"})
        mock_chmod.assert_not_called()
        # One call for the directory + one for the file
        assert mock_run.call_count == 2
        for call_args in mock_run.call_args_list:
            cmd = call_args[0][0]
            assert cmd[0] == "icacls"
            assert "/inheritance:r" in cmd
            assert "/grant:r" in cmd
            assert "TESTDOM\\tester:F" in cmd
        assert load_token("drive") == {"access_token": "test"}


def test_save_token_windows_icacls_failure_rollback(token_dir, monkeypatch):
    """When icacls /grant fails, rollback inheritance so dir stays accessible."""
    monkeypatch.setenv("USERDOMAIN", "TESTDOM")
    with (
        patch("wet_mcp.token_store.os.name", "nt"),
        patch("wet_mcp.token_store.subprocess.run") as mock_run,
        patch("wet_mcp.token_store.getpass.getuser", return_value="tester"),
        patch.object(Path, "chmod"),
    ):
        # Simulate grant failure -> returncode=5
        mock_run.return_value.returncode = 5
        mock_run.return_value.stderr = b"No mapping"
        save_token("drive", {"access_token": "test"})
        # Expect: dir grant fail -> dir rollback; file grant fail -> file rollback = 4 calls
        assert mock_run.call_count == 4
        rollback_cmds = [
            c for c in mock_run.call_args_list if "/inheritance:e" in c[0][0]
        ]
        assert len(rollback_cmds) == 2, "Expected 2 rollback calls (/inheritance:e)"


def test_save_token_windows_icacls_failure_non_fatal(token_dir):
    """icacls failure must not break save_token flow."""
    with (
        patch("wet_mcp.token_store.os.name", "nt"),
        patch(
            "wet_mcp.token_store.subprocess.run",
            side_effect=OSError("icacls missing"),
        ),
        patch("wet_mcp.token_store.getpass.getuser", return_value="tester"),
    ):
        # Should not raise
        save_token("drive", {"access_token": "test"})
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


def test_get_token_dir_for_sub(token_dir, tmp_path):
    """Test _get_token_dir_for_sub helper."""
    assert _get_token_dir_for_sub("user1") == tmp_path / "subs" / "user1" / "tokens"


def test_get_token_path_for_sub(token_dir, tmp_path):
    """Test get_token_path_for_sub returns correct scoped path."""
    expected = tmp_path / "subs" / "user1" / "tokens" / "drive.json"
    assert get_token_path_for_sub("user1", "drive") == expected


def test_save_and_load_token_for_sub(token_dir):
    """Test standard save and load flow for per-sub tokens."""
    sub = "user123"
    token = {"access_token": "sub-token-456", "token_type": "Bearer"}

    save_token_for_sub(sub, "drive", token)
    loaded = load_token_for_sub(sub, "drive")

    assert loaded == token


def test_load_token_for_sub_missing(token_dir):
    """load_token_for_sub returns None if file doesn't exist."""
    assert load_token_for_sub("no-user", "drive") is None


def test_load_token_for_sub_invalid_format(token_dir, tmp_path):
    """load_token_for_sub returns None for malformed JSON or invalid format."""
    sub = "user1"
    path = get_token_path_for_sub(sub, "drive")
    path.parent.mkdir(parents=True, exist_ok=True)

    # Malformed JSON
    path.write_text("not json", encoding="utf-8")
    assert load_token_for_sub(sub, "drive") is None

    # Missing access_token
    path.write_text(json.dumps({"foo": "bar"}), encoding="utf-8")
    assert load_token_for_sub(sub, "drive") is None


def test_read_token_for_sub_alias():
    """Verify read_token_for_sub is an alias for load_token_for_sub."""
    assert read_token_for_sub is load_token_for_sub


def test_load_token_for_sub_non_dict(token_dir, tmp_path):
    """load_token_for_sub returns None if JSON is not a dictionary."""
    sub = "user1"
    path = get_token_path_for_sub(sub, "drive")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps([1, 2, 3]), encoding="utf-8")
    assert load_token_for_sub(sub, "drive") is None


def test_load_token_for_sub_oserror(token_dir):
    """load_token_for_sub handles OSError during read."""
    with patch.object(Path, "exists", side_effect=OSError("disk error")):
        assert load_token_for_sub("user1", "drive") is None
