"""Tests for Google Drive sync token storage and loading."""

from unittest.mock import patch

from wet_mcp.sync import _has_token_available, _load_token, _save_token


def test_load_token_delegates():
    """_load_token delegates to token_store.load_token."""
    with patch(
        "wet_mcp.token_store.load_token", return_value={"access_token": "x"}
    ) as mock:
        result = _load_token()
        assert result == {"access_token": "x"}
        mock.assert_called_once_with("google_drive")


def test_save_token_delegates():
    """_save_token delegates to token_store.save_token."""
    with patch("wet_mcp.token_store.save_token") as mock:
        _save_token({"access_token": "y"})
        mock.assert_called_once_with("google_drive", {"access_token": "y"})


def test_load_token_none():
    """Returns None when no token stored."""
    with patch("wet_mcp.token_store.load_token", return_value=None):
        assert _load_token() is None


def test_has_token_via_load():
    """_has_token_available uses _load_token internally."""
    with patch("wet_mcp.token_store.load_token", return_value={"access_token": "tok"}):
        assert _has_token_available() is True

    with patch("wet_mcp.token_store.load_token", return_value=None):
        assert _has_token_available() is False
