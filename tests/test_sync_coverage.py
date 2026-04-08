"""Tests to improve wet_mcp.sync coverage for Google Drive API code."""

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from wet_mcp.sync import (
    _has_token_available,
    setup_sync,
    sync_full,
)


class TestHasTokenAvailable:
    """Cover _has_token_available function."""

    @patch("wet_mcp.sync._load_token", return_value={"access_token": "x"})
    def test_token_present(self, _mock_load):
        assert _has_token_available() is True

    @patch("wet_mcp.sync._load_token", return_value=None)
    def test_no_token(self, _mock_load):
        assert _has_token_available() is False


class TestRefreshToken:
    """Cover _refresh_token function."""

    @pytest.mark.asyncio
    async def test_success(self):
        from wet_mcp.sync import _refresh_token

        token = {
            "access_token": "old",
            "refresh_token": "refresh123",
            "client_id": "client123",
        }
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "access_token": "new",
            "refresh_token": "new_refresh",
            "expires_in": 3600,
            "token_type": "Bearer",
        }

        with (
            patch("wet_mcp.sync.httpx.AsyncClient") as mock_client,
            patch("wet_mcp.sync._save_token") as mock_save,
        ):
            mock_instance = AsyncMock()
            mock_instance.post = AsyncMock(return_value=mock_response)
            mock_client.return_value.__aenter__ = AsyncMock(return_value=mock_instance)
            mock_client.return_value.__aexit__ = AsyncMock(return_value=None)

            result = await _refresh_token(token)

        assert result is not None
        assert result["access_token"] == "new"
        assert result["refresh_token"] == "new_refresh"
        mock_save.assert_called_once()

    @pytest.mark.asyncio
    async def test_keeps_existing_refresh_token(self):
        from wet_mcp.sync import _refresh_token

        token = {
            "access_token": "old",
            "refresh_token": "keep_this",
            "client_id": "client123",
        }
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "access_token": "new",
            "expires_in": 3600,
        }

        with (
            patch("wet_mcp.sync.httpx.AsyncClient") as mock_client,
            patch("wet_mcp.sync._save_token"),
        ):
            mock_instance = AsyncMock()
            mock_instance.post = AsyncMock(return_value=mock_response)
            mock_client.return_value.__aenter__ = AsyncMock(return_value=mock_instance)
            mock_client.return_value.__aexit__ = AsyncMock(return_value=None)

            result = await _refresh_token(token)

        assert result is not None
        assert result["refresh_token"] == "keep_this"

    @pytest.mark.asyncio
    async def test_failure(self):
        from wet_mcp.sync import _refresh_token

        token = {"access_token": "old", "refresh_token": "r", "client_id": "c"}
        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.text = "invalid_grant"

        with patch("wet_mcp.sync.httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.post = AsyncMock(return_value=mock_response)
            mock_client.return_value.__aenter__ = AsyncMock(return_value=mock_instance)
            mock_client.return_value.__aexit__ = AsyncMock(return_value=None)

            result = await _refresh_token(token)

        assert result is None


class TestGetValidToken:
    """Cover _get_valid_token function."""

    @pytest.mark.asyncio
    async def test_no_token(self):
        from wet_mcp.sync import _get_valid_token

        with patch("wet_mcp.sync._load_token", return_value=None):
            assert await _get_valid_token() is None

    @pytest.mark.asyncio
    async def test_valid_token(self):
        from wet_mcp.sync import _get_valid_token

        token = {"access_token": "valid", "expiry": time.time() + 3600}
        with patch("wet_mcp.sync._load_token", return_value=token):
            assert await _get_valid_token() == token

    @pytest.mark.asyncio
    async def test_expired_refreshes(self):
        from wet_mcp.sync import _get_valid_token

        old = {"access_token": "exp", "expiry": time.time() - 100}
        new = {"access_token": "new", "expiry": time.time() + 3600}
        with (
            patch("wet_mcp.sync._load_token", return_value=old),
            patch("wet_mcp.sync._refresh_token", return_value=new),
        ):
            assert await _get_valid_token() == new


class TestSyncFullTokenPaths:
    """Cover sync_full token resolution paths."""

    @pytest.mark.asyncio
    @patch("wet_mcp.sync.settings")
    @patch("wet_mcp.sync._has_token_available", return_value=False)
    async def test_no_token_auth_fails(self, _mock_has, mock_settings):
        mock_settings.sync_enabled = True
        mock_settings.google_drive_client_id = "client123"

        result = await sync_full(MagicMock())
        assert result["status"] == "error"
        assert "token" in result["message"].lower()

    @pytest.mark.asyncio
    @patch("wet_mcp.sync.settings")
    @patch("wet_mcp.sync._has_token_available", return_value=True)
    @patch("wet_mcp.sync._get_valid_token", return_value=None)
    async def test_token_refresh_fails(self, _mock_valid, _mock_has, mock_settings):
        mock_settings.sync_enabled = True
        mock_settings.google_drive_client_id = "client123"

        result = await sync_full(MagicMock())
        assert result["status"] == "error"
        assert "expired" in result["message"].lower()


class TestSetupSyncTokenSuccess:
    """Cover setup_sync with successful auth."""

    @patch("wet_mcp.sync.settings")
    @patch("wet_mcp.sync.asyncio.run", return_value=True)
    def test_success(self, _mock_run, mock_settings, capsys):
        mock_settings.google_drive_client_id = "client123"

        setup_sync()

        captured = capsys.readouterr()
        assert "SUCCESS" in captured.out
        assert "SYNC_ENABLED" in captured.out
        assert "GOOGLE_DRIVE_CLIENT_ID" in captured.out

    @patch("wet_mcp.sync.settings")
    def test_auth_fails(self, mock_settings):
        mock_settings.google_drive_client_id = "client123"

        with (
            patch("wet_mcp.sync.asyncio.run", return_value=False),
            pytest.raises(SystemExit),
        ):
            setup_sync()
