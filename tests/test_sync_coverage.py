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


class TestSetupGoogleAuth:
    """Cover setup_google_auth function."""

    @pytest.mark.asyncio
    @patch("wet_mcp.sync.settings")
    async def test_missing_config(self, mock_settings):
        from wet_mcp.sync import setup_google_auth

        mock_settings.google_drive_client_id = None
        assert await setup_google_auth() is False

    @pytest.mark.asyncio
    @patch("wet_mcp.sync.settings")
    @patch("wet_mcp.sync.httpx.AsyncClient")
    async def test_device_code_request_failure(self, mock_client, mock_settings):
        from wet_mcp.sync import setup_google_auth

        mock_settings.google_drive_client_id = "c"
        mock_settings.google_drive_client_secret = "s"

        mock_resp = MagicMock()
        mock_resp.status_code = 400
        mock_resp.text = "error"
        mock_instance = AsyncMock()
        mock_instance.post = AsyncMock(return_value=mock_resp)
        mock_client.return_value.__aenter__ = AsyncMock(return_value=mock_instance)

        assert await setup_google_auth() is False

    @pytest.mark.asyncio
    @patch("wet_mcp.sync.settings")
    @patch("wet_mcp.sync.httpx.AsyncClient")
    @patch("wet_mcp.sync._save_token")
    @patch("wet_mcp.sync.asyncio.sleep")
    async def test_success_path_stderr(
        self, mock_sleep, mock_save, mock_client, mock_settings, capsys
    ):
        from wet_mcp.sync import setup_google_auth

        mock_settings.google_drive_client_id = "c"
        mock_settings.google_drive_client_secret = "s"

        # Device code response
        resp1 = MagicMock()
        resp1.status_code = 200
        resp1.json.return_value = {
            "device_code": "dc",
            "user_code": "uc",
            "verification_url": "url",
            "interval": 1,
            "expires_in": 60,
        }

        # Token response
        resp2 = MagicMock()
        resp2.status_code = 200
        resp2.json.return_value = {
            "access_token": "at",
            "refresh_token": "rt",
            "expires_in": 3600,
        }

        mock_instance = AsyncMock()
        mock_instance.post = AsyncMock(side_effect=[resp1, resp2])
        mock_client.return_value.__aenter__ = AsyncMock(return_value=mock_instance)

        assert await setup_google_auth() is True
        mock_save.assert_called_once()
        captured = capsys.readouterr()
        assert "Visit: url" in captured.err
        assert "Enter code: uc" in captured.err

    @pytest.mark.asyncio
    @patch("wet_mcp.sync.settings")
    @patch("wet_mcp.sync.httpx.AsyncClient")
    @patch("wet_mcp.sync._save_token")
    @patch("wet_mcp.sync.asyncio.sleep")
    async def test_success_path_relay(
        self, mock_sleep, mock_save, mock_client, mock_settings
    ):
        from wet_mcp.sync import setup_google_auth

        mock_settings.google_drive_client_id = "c"
        mock_settings.google_drive_client_secret = "s"

        resp_device = MagicMock()
        resp_device.status_code = 200
        resp_device.json.return_value = {
            "device_code": "dc",
            "user_code": "uc",
            "verification_url": "url",
            "interval": 1,
            "expires_in": 60,
        }

        resp_relay = MagicMock()
        resp_relay.status_code = 200

        resp_token = MagicMock()
        resp_token.status_code = 200
        resp_token.json.return_value = {"access_token": "at"}

        mock_instance = AsyncMock()
        mock_instance.post = AsyncMock(
            side_effect=[resp_device, resp_relay, resp_token]
        )
        mock_client.return_value.__aenter__ = AsyncMock(return_value=mock_instance)

        assert (
            await setup_google_auth(relay_url="http://relay", session_id="s123") is True
        )
        # Verify relay call
        relay_call = mock_instance.post.call_args_list[1]
        assert "http://relay/api/sessions/s123/messages" in relay_call.args[0]

    @pytest.mark.asyncio
    @patch("wet_mcp.sync.settings")
    @patch("wet_mcp.sync.httpx.AsyncClient")
    @patch("wet_mcp.sync.asyncio.sleep")
    async def test_polling_behaviors(self, mock_sleep, mock_client, mock_settings):
        from wet_mcp.sync import setup_google_auth

        mock_settings.google_drive_client_id = "c"
        mock_settings.google_drive_client_secret = "s"

        resp_device = MagicMock()
        resp_device.status_code = 200
        resp_device.json.return_value = {
            "device_code": "dc",
            "user_code": "uc",
            "verification_url": "url",
            "interval": 1,
            "expires_in": 60,
        }

        # 1. Pending, 2. Slow down, 3. Terminal error
        resp_pending = MagicMock(status_code=400)
        resp_pending.json.return_value = {"error": "authorization_pending"}

        resp_slow = MagicMock(status_code=400)
        resp_slow.json.return_value = {"error": "slow_down"}

        resp_denied = MagicMock(status_code=400)
        resp_denied.json.return_value = {"error": "access_denied"}

        mock_instance = AsyncMock()
        mock_instance.post = AsyncMock(
            side_effect=[resp_device, resp_pending, resp_slow, resp_denied]
        )
        mock_client.return_value.__aenter__ = AsyncMock(return_value=mock_instance)

        assert await setup_google_auth() is False
        assert mock_instance.post.call_count == 4

    @pytest.mark.asyncio
    @patch("wet_mcp.sync.settings")
    @patch("wet_mcp.sync.httpx.AsyncClient")
    @patch("wet_mcp.sync.time.time")
    @patch("wet_mcp.sync.asyncio.sleep")
    async def test_timeout(self, mock_sleep, mock_time, mock_client, mock_settings):
        from wet_mcp.sync import setup_google_auth

        mock_settings.google_drive_client_id = "c"
        mock_settings.google_drive_client_secret = "s"

        mock_time.side_effect = [
            1000,
            1001,
            2000,
        ]  # Start, presentation, poll 1 (expired)

        resp_device = MagicMock()
        resp_device.status_code = 200
        resp_device.json.return_value = {
            "device_code": "dc",
            "user_code": "uc",
            "verification_url": "url",
            "interval": 1,
            "expires_in": 60,
        }

        mock_instance = AsyncMock()
        mock_instance.post = AsyncMock(return_value=resp_device)
        mock_client.return_value.__aenter__ = AsyncMock(return_value=mock_instance)

        assert await setup_google_auth() is False
