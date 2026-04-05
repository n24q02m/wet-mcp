"""Tests for src/wet_mcp/sync.py -- Google Drive sync utilities.

Covers token management, Google Drive API operations, sync flow,
and auto-sync lifecycle. All tests use mocks to avoid requiring
Google Drive access or network.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

import wet_mcp.sync
from wet_mcp import sync
from wet_mcp.sync import (
    _has_token_available,
    setup_sync,
    start_auto_sync,
    stop_auto_sync,
)

# -----------------------------------------------------------------------
# Token management
# -----------------------------------------------------------------------


class TestTokenManagement:
    def test_has_token_available_true(self):
        """Returns True when token exists."""
        with patch("wet_mcp.sync._load_token", return_value={"access_token": "abc"}):
            assert _has_token_available() is True

    def test_has_token_available_false(self):
        """Returns False when no token."""
        with patch("wet_mcp.sync._load_token", return_value=None):
            assert _has_token_available() is False

    @pytest.mark.asyncio
    async def test_refresh_token_success(self):
        """Refreshes expired token successfully."""
        from wet_mcp.sync import _refresh_token

        token = {
            "access_token": "old",
            "refresh_token": "refresh123",
            "client_id": "client123",
        }

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "access_token": "new_token",
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
            assert result["access_token"] == "new_token"
            assert result["refresh_token"] == "refresh123"
            mock_save.assert_called_once()

    @pytest.mark.asyncio
    async def test_refresh_token_failure(self):
        """Returns None when refresh fails."""
        from wet_mcp.sync import _refresh_token

        token = {
            "access_token": "old",
            "refresh_token": "refresh123",
            "client_id": "client123",
        }

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


# -----------------------------------------------------------------------
# check_health
# -----------------------------------------------------------------------


class TestCheckHealth:
    @pytest.mark.asyncio
    async def test_health_ok(self):
        """Returns True when Drive API is accessible."""
        mock_response = MagicMock()
        mock_response.status_code = 200

        with (
            patch(
                "wet_mcp.sync._get_valid_token",
                return_value={"access_token": "t"},
            ),
            patch("wet_mcp.sync._drive_request", return_value=mock_response),
        ):
            assert await sync.check_health() is True

    @pytest.mark.asyncio
    async def test_health_no_token(self):
        """Returns False when no token."""
        with patch("wet_mcp.sync._get_valid_token", return_value=None):
            assert await sync.check_health() is False

    @pytest.mark.asyncio
    async def test_health_api_error(self):
        """Returns False on API error."""
        with (
            patch(
                "wet_mcp.sync._get_valid_token",
                return_value={"access_token": "t"},
            ),
            patch("wet_mcp.sync._drive_request", side_effect=Exception("err")),
        ):
            assert await sync.check_health() is False


# -----------------------------------------------------------------------
# setup_google_auth (Device Code flow)
# -----------------------------------------------------------------------


class TestSetupGoogleAuth:
    @pytest.mark.asyncio
    async def test_no_client_id(self):
        """Returns False when client ID not configured."""
        with patch("wet_mcp.sync.settings.google_drive_client_id", ""):
            assert await sync.setup_google_auth() is False

    @pytest.mark.asyncio
    async def test_device_code_request_failure(self):
        """Returns False when device code request fails."""
        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.text = "Bad Request"

        with (
            patch("wet_mcp.sync.settings.google_drive_client_id", "client123"),
            patch("wet_mcp.sync.httpx.AsyncClient") as mock_client,
        ):
            mock_instance = AsyncMock()
            mock_instance.post = AsyncMock(return_value=mock_response)
            mock_client.return_value.__aenter__ = AsyncMock(return_value=mock_instance)
            mock_client.return_value.__aexit__ = AsyncMock(return_value=None)

            assert await sync.setup_google_auth() is False

    @pytest.mark.asyncio
    async def test_setup_google_auth_success(self):
        """Full success path for Google OAuth device code flow."""
        device_response = MagicMock(spec=httpx.Response)
        device_response.status_code = 200
        device_response.json.return_value = {
            "device_code": "dev123",
            "user_code": "USER-123",
            "verification_url": "https://google.com/device",
            "interval": 1,
            "expires_in": 60,
        }

        token_response = MagicMock(spec=httpx.Response)
        token_response.status_code = 200
        token_response.json.return_value = {
            "access_token": "acc123",
            "refresh_token": "ref123",
            "expires_in": 3600,
            "token_type": "Bearer",
        }

        # Mock httpx.AsyncClient context manager
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.post.side_effect = [device_response, token_response]

        # We need a side effect for __aenter__ to return the same mock_client
        mock_client.__aenter__.return_value = mock_client

        with (
            patch("wet_mcp.sync.settings.google_drive_client_id", "client123"),
            patch("wet_mcp.sync.settings.google_drive_client_secret", "secret123"),
            patch("wet_mcp.sync.httpx.AsyncClient", return_value=mock_client),
            patch("wet_mcp.sync.asyncio.sleep", return_value=None),
            patch("wet_mcp.sync._save_token") as mock_save,
        ):
            # We must mock time.time so it doesn't expire during loop
            # The loop uses time.time() < deadline
            # deadline = 1000.0 + 60 = 1060.0
            # Next call to time.time() in loop should be < 1060.0

            # Use a side effect for time.time to simulate passage of time or stay constant
            # First call: deadline calculation (1000.0)
            # Second call: while loop check (1001.0)
            # Third call: token expiry calculation (1001.0 + 3600)
            with patch("wet_mcp.sync.time.time", side_effect=[1000.0, 1001.0, 1001.0]):
                result = await sync.setup_google_auth()

            assert result is True
            mock_save.assert_called_once()
            token = mock_save.call_args[0][0]
            assert token["access_token"] == "acc123"
            assert token["refresh_token"] == "ref123"
            assert token["expiry"] == 1001.0 + 3600

    @pytest.mark.asyncio
    async def test_setup_google_auth_relay_success(self):
        """Device code flow with relay messaging."""
        device_response = MagicMock(spec=httpx.Response)
        device_response.status_code = 200
        device_response.json.return_value = {
            "device_code": "dev123",
            "user_code": "USER-123",
            "verification_url": "https://google.com/device",
            "interval": 1,
            "expires_in": 60,
        }

        relay_response = MagicMock(spec=httpx.Response)
        relay_response.status_code = 200

        token_response = MagicMock(spec=httpx.Response)
        token_response.status_code = 200
        token_response.json.return_value = {
            "access_token": "acc123",
            "expires_in": 3600,
        }

        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.post.side_effect = [device_response, relay_response, token_response]
        mock_client.__aenter__.return_value = mock_client

        with (
            patch("wet_mcp.sync.settings.google_drive_client_id", "client123"),
            patch("wet_mcp.sync.settings.google_drive_client_secret", "secret123"),
            patch("wet_mcp.sync.httpx.AsyncClient", return_value=mock_client),
            patch("wet_mcp.sync.asyncio.sleep", return_value=None),
            patch("wet_mcp.sync._save_token"),
        ):
            with patch("wet_mcp.sync.time.time", side_effect=[1000.0, 1001.0, 1001.0]):
                result = await sync.setup_google_auth(
                    relay_url="https://relay.io", session_id="sess123"
                )

            assert result is True
            # Verify relay POST was called
            relay_call = mock_client.post.call_args_list[1]
            assert relay_call[0][0] == "https://relay.io/api/sessions/sess123/messages"
            assert relay_call[1]["json"]["type"] == "oauth_device_code"

    @pytest.mark.asyncio
    async def test_setup_google_auth_polling_states(self):
        """Polling states: authorization_pending and slow_down."""
        device_response = MagicMock(spec=httpx.Response)
        device_response.status_code = 200
        device_response.json.return_value = {
            "device_code": "dev123",
            "user_code": "USER-123",
            "verification_url": "https://google.com/device",
            "interval": 1,
            "expires_in": 60,
        }

        # Sequence of token responses
        pending_response = MagicMock(spec=httpx.Response)
        pending_response.status_code = 400
        pending_response.json.return_value = {"error": "authorization_pending"}

        slowdown_response = MagicMock(spec=httpx.Response)
        slowdown_response.status_code = 400
        slowdown_response.json.return_value = {"error": "slow_down"}

        success_response = MagicMock(spec=httpx.Response)
        success_response.status_code = 200
        success_response.json.return_value = {
            "access_token": "acc123",
            "expires_in": 3600,
        }

        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.post.side_effect = [
            device_response,
            pending_response,
            slowdown_response,
            success_response,
        ]
        mock_client.__aenter__.return_value = mock_client

        with (
            patch("wet_mcp.sync.settings.google_drive_client_id", "client123"),
            patch("wet_mcp.sync.settings.google_drive_client_secret", "secret123"),
            patch("wet_mcp.sync.httpx.AsyncClient", return_value=mock_client),
            patch("wet_mcp.sync.asyncio.sleep", return_value=None) as mock_sleep,
            patch("wet_mcp.sync._save_token"),
        ):
            with patch(
                "wet_mcp.sync.time.time",
                side_effect=[1000.0, 1001.0, 1002.0, 1003.0, 1003.0],
            ):
                result = await sync.setup_google_auth()

            assert result is True
            # Verify 3 sleeps (one after each polling attempt before success)
            assert mock_sleep.call_count == 3
            # Check interval increment for slow_down
            # First sleep uses interval=1
            # Second sleep uses interval=1 (after authorization_pending)
            # Third sleep uses interval=2 (after slow_down)
            mock_sleep.assert_any_call(1)
            mock_sleep.assert_any_call(2)

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "error_code", ["access_denied", "expired_token", "invalid_grant"]
    )
    async def test_setup_google_auth_error_conditions(self, error_code):
        """Termination on access_denied, expired_token, or unexpected errors."""
        device_response = MagicMock(spec=httpx.Response)
        device_response.status_code = 200
        device_response.json.return_value = {
            "device_code": "dev123",
            "user_code": "U",
            "verification_url": "V",
            "interval": 1,
            "expires_in": 60,
        }

        error_response = MagicMock(spec=httpx.Response)
        error_response.status_code = 400
        error_response.json.return_value = {"error": error_code}

        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.post.side_effect = [device_response, error_response]
        mock_client.__aenter__.return_value = mock_client

        with (
            patch("wet_mcp.sync.settings.google_drive_client_id", "client123"),
            patch("wet_mcp.sync.settings.google_drive_client_secret", "secret123"),
            patch("wet_mcp.sync.httpx.AsyncClient", return_value=mock_client),
            patch("wet_mcp.sync.asyncio.sleep", return_value=None),
        ):
            with patch("wet_mcp.sync.time.time", side_effect=[1000.0, 1001.0]):
                result = await sync.setup_google_auth()
            assert result is False

    @pytest.mark.asyncio
    async def test_setup_google_auth_polling_exception(self):
        """Exception during token polling."""
        device_response = MagicMock(spec=httpx.Response)
        device_response.status_code = 200
        device_response.json.return_value = {
            "device_code": "dev123",
            "user_code": "U",
            "verification_url": "V",
            "interval": 1,
            "expires_in": 60,
        }

        mock_client = AsyncMock(spec=httpx.AsyncClient)
        # First call success (device), second call (token) raises exception
        mock_client.post.side_effect = [device_response, Exception("Network error")]
        mock_client.__aenter__.return_value = mock_client

        with (
            patch("wet_mcp.sync.settings.google_drive_client_id", "client123"),
            patch("wet_mcp.sync.settings.google_drive_client_secret", "secret123"),
            patch("wet_mcp.sync.httpx.AsyncClient", return_value=mock_client),
            patch("wet_mcp.sync.asyncio.sleep", return_value=None),
        ):
            with patch("wet_mcp.sync.time.time", side_effect=[1000.0, 1001.0]):
                result = await sync.setup_google_auth()
            assert result is False

    @pytest.mark.asyncio
    async def test_setup_google_auth_expired_deadline(self):
        """Termination on device code expiration (deadline)."""
        device_response = MagicMock(spec=httpx.Response)
        device_response.status_code = 200
        device_response.json.return_value = {
            "device_code": "dev123",
            "user_code": "U",
            "verification_url": "V",
            "interval": 1,
            "expires_in": 10,
        }

        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.post.return_value = device_response
        mock_client.__aenter__.return_value = mock_client

        with (
            patch("wet_mcp.sync.settings.google_drive_client_id", "client123"),
            patch("wet_mcp.sync.settings.google_drive_client_secret", "secret123"),
            patch("wet_mcp.sync.httpx.AsyncClient", return_value=mock_client),
            patch("wet_mcp.sync.asyncio.sleep", return_value=None),
        ):
            # First time.time() for deadline calculation (1000.0)
            # Second time.time() for while check (1011.0, which is > 1000.0 + 10)
            with patch("wet_mcp.sync.time.time", side_effect=[1000.0, 1011.0]):
                result = await sync.setup_google_auth()
            assert result is False


class TestSetupSync:
    def test_no_client_id(self):
        """setup_sync exits when GOOGLE_DRIVE_CLIENT_ID is not set."""
        import pytest

        with patch("wet_mcp.sync.settings") as mock_settings:
            mock_settings.google_drive_client_id = ""
            with pytest.raises(SystemExit, match="1"):
                setup_sync()

    def test_success(self, capsys):
        """setup_sync prints success on successful auth."""
        with (
            patch("wet_mcp.sync.settings") as mock_settings,
            patch("wet_mcp.sync.asyncio.run", return_value=True),
        ):
            mock_settings.google_drive_client_id = "client123"
            setup_sync()
            captured = capsys.readouterr()
            assert "SUCCESS" in captured.out
            assert "SYNC_ENABLED" in captured.out

    def test_failure(self):
        """setup_sync exits on auth failure."""
        import pytest

        with (
            patch("wet_mcp.sync.settings") as mock_settings,
            patch("wet_mcp.sync.asyncio.run", return_value=False),
        ):
            mock_settings.google_drive_client_id = "client123"
            with pytest.raises(SystemExit, match="1"):
                setup_sync()


class TestStartAutoSync:
    def teardown_method(self):
        """Ensure _sync_task is reset after each test."""
        if wet_mcp.sync._sync_task and not wet_mcp.sync._sync_task.done():
            wet_mcp.sync._sync_task.cancel()
        wet_mcp.sync._sync_task = None

    def test_sync_disabled(self):
        """Task is not started if sync is disabled."""
        mock_db = MagicMock()
        with (
            patch("wet_mcp.sync.settings") as mock_settings,
            patch("wet_mcp.sync.asyncio.create_task") as mock_create_task,
        ):
            mock_settings.sync_enabled = False
            start_auto_sync(mock_db)
            mock_create_task.assert_not_called()

    def test_no_client_id_still_starts(self):
        """Task is started even if client ID is empty (sync_enabled=True)."""
        mock_db = MagicMock()
        with (
            patch("wet_mcp.sync.settings") as mock_settings,
            patch("wet_mcp.sync.asyncio.create_task") as mock_create_task,
            patch("wet_mcp.sync._auto_sync_loop"),
        ):
            mock_settings.sync_enabled = True
            mock_settings.google_drive_client_id = ""
            mock_settings.sync_interval = 60
            start_auto_sync(mock_db)
            mock_create_task.assert_called_once()

    def test_invalid_interval(self):
        """Task is not started if interval is <= 0."""
        mock_db = MagicMock()
        with (
            patch("wet_mcp.sync.settings") as mock_settings,
            patch("wet_mcp.sync.asyncio.create_task") as mock_create_task,
        ):
            mock_settings.sync_enabled = True
            mock_settings.google_drive_client_id = "client123"
            mock_settings.sync_interval = 0
            start_auto_sync(mock_db)
            mock_create_task.assert_not_called()

    def test_already_running(self):
        """Task is not started if already running."""
        mock_task = MagicMock()
        mock_task.done.return_value = False
        wet_mcp.sync._sync_task = mock_task

        mock_db = MagicMock()
        with (
            patch("wet_mcp.sync.settings") as mock_settings,
            patch("wet_mcp.sync.asyncio.create_task") as mock_create_task,
        ):
            mock_settings.sync_enabled = True
            mock_settings.google_drive_client_id = "client123"
            mock_settings.sync_interval = 60

            start_auto_sync(mock_db)
            mock_create_task.assert_not_called()

    def test_starts_task(self):
        """Task is started correctly when conditions are met."""
        wet_mcp.sync._sync_task = None

        mock_db = MagicMock()
        with (
            patch("wet_mcp.sync.settings") as mock_settings,
            patch("wet_mcp.sync.asyncio.create_task") as mock_create_task,
            patch("wet_mcp.sync._auto_sync_loop") as mock_loop,
        ):
            mock_settings.sync_enabled = True
            mock_settings.google_drive_client_id = "client123"
            mock_settings.sync_interval = 60

            dummy_task = MagicMock()
            mock_create_task.return_value = dummy_task

            start_auto_sync(mock_db)

            mock_create_task.assert_called_once()
            assert wet_mcp.sync._sync_task == dummy_task
            mock_loop.assert_called_once_with(mock_db)


class TestStopAutoSync:
    def test_no_task(self):
        wet_mcp.sync._sync_task = None
        stop_auto_sync()
        assert wet_mcp.sync._sync_task is None

    def test_task_already_done(self):

        future = asyncio.Future()
        future.set_result(None)
        wet_mcp.sync._sync_task = future  # ty: ignore[invalid-assignment]
        stop_auto_sync()
        # Task is done, should not be cancelled or cleared
        assert wet_mcp.sync._sync_task is future

    def test_running_task_cancelled(self):
        mock_task = MagicMock()
        mock_task.done.return_value = False
        wet_mcp.sync._sync_task = mock_task
        stop_auto_sync()
        mock_task.cancel.assert_called_once()
        assert wet_mcp.sync._sync_task is None


class TestDriveRequest:
    async def test_authenticated_request(self):
        from wet_mcp.sync import _drive_request

        token = {"access_token": "test_token"}
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.request.return_value = mock_response
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            result = await _drive_request("GET", "https://example.com", token)

        assert result.status_code == 200
        # Verify auth header was set
        call_kwargs = mock_client.request.call_args
        assert "Authorization" in call_kwargs.kwargs.get(
            "headers", {}
        ) or "Authorization" in call_kwargs[1].get("headers", {})
