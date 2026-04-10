"""Tests for src/wet_mcp/sync.py -- Google Drive sync utilities.

Covers token management, Google Drive API operations, sync flow,
and auto-sync lifecycle. All tests use mocks to avoid requiring
Google Drive access or network.
"""

import asyncio
import time
from pathlib import Path
from typing import cast
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from wet_mcp import sync
from wet_mcp.sync import (
    _has_token_available,
    check_health,
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

    @pytest.mark.asyncio
    async def test_refresh_token_missing_fields(self):
        """Returns None when token has no refresh_token."""
        from wet_mcp.sync import _refresh_token

        result = await _refresh_token({"access_token": "old"})
        assert result is None

    @pytest.mark.asyncio
    async def test_get_valid_token_no_token(self):
        """Returns None when no token stored."""
        from wet_mcp.sync import _get_valid_token

        with patch("wet_mcp.sync._load_token", return_value=None):
            result = await _get_valid_token()
            assert result is None

    @pytest.mark.asyncio
    async def test_get_valid_token_not_expired(self):
        """Returns token when not expired."""
        from wet_mcp.sync import _get_valid_token

        token = {"access_token": "valid", "expiry": time.time() + 3600}
        with patch("wet_mcp.sync._load_token", return_value=token):
            result = await _get_valid_token()
            assert result == token

    @pytest.mark.asyncio
    async def test_get_valid_token_expired_refreshes(self):
        """Refreshes expired token."""
        from wet_mcp.sync import _get_valid_token

        old_token = {
            "access_token": "expired",
            "expiry": time.time() - 100,
            "refresh_token": "refresh",
            "client_id": "client",
        }
        new_token = {"access_token": "new", "expiry": time.time() + 3600}

        with (
            patch("wet_mcp.sync._load_token", return_value=old_token),
            patch("wet_mcp.sync._refresh_token", return_value=new_token),
        ):
            result = await _get_valid_token()
            assert result == new_token


# -----------------------------------------------------------------------
# Google Drive API helpers
# -----------------------------------------------------------------------


class TestDriveHelpers:
    def setup_method(self):
        """Clear folder ID cache between tests."""
        import wet_mcp.sync as sync_mod

        sync_mod._folder_id_cache.clear()

    @pytest.mark.asyncio
    async def test_find_or_create_folder_existing(self):
        """Finds existing folder by name."""
        from wet_mcp.sync import _find_or_create_folder

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "files": [{"id": "folder123", "name": "test"}]
        }

        with (
            patch("wet_mcp.sync._drive_request", return_value=mock_response),
            patch("wet_mcp.sync._load_folder_id", return_value=None),
            patch("wet_mcp.sync._save_folder_id"),
        ):
            result = await _find_or_create_folder({"access_token": "t"}, "test")
            assert result == "folder123"

    @pytest.mark.asyncio
    async def test_find_or_create_folder_creates_new(self):
        """Creates folder when not found (after 3 search retries)."""
        from wet_mcp.sync import _find_or_create_folder

        search_response = MagicMock()
        search_response.status_code = 200
        search_response.json.return_value = {"files": []}

        create_response = MagicMock()
        create_response.status_code = 200
        create_response.json.return_value = {"id": "new_folder"}

        with (
            patch(
                "wet_mcp.sync._drive_request",
                side_effect=[
                    search_response,
                    search_response,
                    search_response,
                    create_response,
                ],
            ),
            patch("wet_mcp.sync._load_folder_id", return_value=None),
            patch("wet_mcp.sync._save_folder_id"),
            patch("asyncio.sleep", return_value=None),
        ):
            result = await _find_or_create_folder({"access_token": "t"}, "test")
            assert result == "new_folder"

    @pytest.mark.asyncio
    async def test_find_or_create_folder_failure(self):
        """Returns None on API failure."""
        from wet_mcp.sync import _find_or_create_folder

        search_response = MagicMock()
        search_response.status_code = 200
        search_response.json.return_value = {"files": []}

        create_response = MagicMock()
        create_response.status_code = 500
        create_response.text = "Internal Error"

        with (
            patch(
                "wet_mcp.sync._drive_request",
                side_effect=[
                    search_response,
                    search_response,
                    search_response,
                    create_response,
                ],
            ),
            patch("wet_mcp.sync._load_folder_id", return_value=None),
            patch("wet_mcp.sync._save_folder_id"),
            patch("asyncio.sleep", return_value=None),
        ):
            result = await _find_or_create_folder({"access_token": "t"}, "test")
            assert result is None

    @pytest.mark.asyncio
    async def test_find_or_create_folder_uses_cached_id(self):
        """Uses cached folder ID and verifies it still exists."""
        from wet_mcp.sync import _find_or_create_folder, _folder_id_cache

        _folder_id_cache["test"] = "cached_id"

        verify_response = MagicMock()
        verify_response.status_code = 200
        verify_response.json.return_value = {"id": "cached_id", "trashed": False}

        with patch("wet_mcp.sync._drive_request", return_value=verify_response):
            result = await _find_or_create_folder({"access_token": "t"}, "test")
            assert result == "cached_id"

    @pytest.mark.asyncio
    async def test_find_or_create_folder_disk_cache(self):
        """Falls back to disk-cached folder ID."""
        from wet_mcp.sync import _find_or_create_folder

        verify_response = MagicMock()
        verify_response.status_code = 200
        verify_response.json.return_value = {"id": "disk_id", "trashed": False}

        with (
            patch("wet_mcp.sync._drive_request", return_value=verify_response),
            patch("wet_mcp.sync._load_folder_id", return_value="disk_id"),
        ):
            result = await _find_or_create_folder({"access_token": "t"}, "test")
            assert result == "disk_id"

    @pytest.mark.asyncio
    async def test_find_file_in_folder_found(self):
        """Finds file in folder."""
        from wet_mcp.sync import _find_file_in_folder

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "files": [{"id": "file1", "name": "docs.db", "modifiedTime": "t"}]
        }

        with patch("wet_mcp.sync._drive_request", return_value=mock_response):
            result = await _find_file_in_folder(
                {"access_token": "t"}, "folder1", "docs.db"
            )
            assert result is not None
            assert result["id"] == "file1"

    @pytest.mark.asyncio
    async def test_find_file_in_folder_not_found(self):
        """Returns None when file not found."""
        from wet_mcp.sync import _find_file_in_folder

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"files": []}

        with patch("wet_mcp.sync._drive_request", return_value=mock_response):
            result = await _find_file_in_folder(
                {"access_token": "t"}, "folder1", "docs.db"
            )
            assert result is None

    @pytest.mark.asyncio
    async def test_upload_file_update_existing(self):
        """Updates existing file content."""
        from wet_mcp.sync import _upload_file

        mock_response = MagicMock()
        mock_response.status_code = 200

        with (
            patch("wet_mcp.sync._drive_request", return_value=mock_response),
            patch(
                "wet_mcp.sync.asyncio.to_thread",
                return_value=b"db_content",
            ),
        ):
            result = await _upload_file(
                {"access_token": "t"},
                Path("/mock/docs.db"),
                "folder1",
                "existing_file_id",
            )
            assert result is True

    @pytest.mark.asyncio
    async def test_upload_file_create_new(self):
        """Creates new file in folder."""
        from wet_mcp.sync import _upload_file

        mock_response = MagicMock()
        mock_response.status_code = 200

        with (
            patch("wet_mcp.sync._drive_request", return_value=mock_response),
            patch(
                "wet_mcp.sync.asyncio.to_thread",
                return_value=b"db_content",
            ),
        ):
            result = await _upload_file(
                {"access_token": "t"},
                Path("/mock/docs.db"),
                "folder1",
                None,
            )
            assert result is True

    @pytest.mark.asyncio
    async def test_upload_file_failure(self):
        """Returns False on upload failure."""
        from wet_mcp.sync import _upload_file

        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = "Server Error"

        with (
            patch("wet_mcp.sync._drive_request", return_value=mock_response),
            patch(
                "wet_mcp.sync.asyncio.to_thread",
                return_value=b"db_content",
            ),
        ):
            result = await _upload_file(
                {"access_token": "t"},
                Path("/mock/docs.db"),
                "folder1",
                "file1",
            )
            assert result is False

    @pytest.mark.asyncio
    async def test_download_file_success(self):
        """Downloads file successfully."""
        from wet_mcp.sync import _download_file

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = b"downloaded_content"

        with (
            patch("wet_mcp.sync._drive_request", return_value=mock_response),
            patch("wet_mcp.sync.asyncio.to_thread") as mock_thread,
            patch("pathlib.Path.mkdir"),
        ):
            result = await _download_file(
                {"access_token": "t"}, "file1", Path("/tmp/out.db")
            )
            assert result is True
            mock_thread.assert_called()

    @pytest.mark.asyncio
    async def test_download_file_failure(self):
        """Returns False on download failure."""
        from wet_mcp.sync import _download_file

        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_response.text = "Not Found"

        with patch("wet_mcp.sync._drive_request", return_value=mock_response):
            result = await _download_file(
                {"access_token": "t"}, "file1", Path("/tmp/out.db")
            )
            assert result is False


# -----------------------------------------------------------------------
# sync_push / sync_pull
# -----------------------------------------------------------------------


class TestSyncPush:
    @pytest.mark.asyncio
    async def test_push_success(self):
        """Pushes file to Google Drive successfully."""
        with (
            patch(
                "wet_mcp.sync._get_valid_token",
                return_value={"access_token": "t"},
            ),
            patch("wet_mcp.sync._find_or_create_folder", return_value="folder1"),
            patch(
                "wet_mcp.sync._find_file_in_folder",
                return_value={"id": "file1"},
            ),
            patch("wet_mcp.sync._upload_file", return_value=True),
        ):
            result = await sync.sync_push(Path("/db/docs.db"), "wet-mcp")
            assert result is True

    @pytest.mark.asyncio
    async def test_push_no_token(self):
        """Returns False when no token available."""
        with patch("wet_mcp.sync._get_valid_token", return_value=None):
            result = await sync.sync_push(Path("/db/docs.db"), "wet-mcp")
            assert result is False

    @pytest.mark.asyncio
    async def test_push_no_folder(self):
        """Returns False when folder creation fails."""
        with (
            patch(
                "wet_mcp.sync._get_valid_token",
                return_value={"access_token": "t"},
            ),
            patch("wet_mcp.sync._find_or_create_folder", return_value=None),
        ):
            result = await sync.sync_push(Path("/db/docs.db"), "wet-mcp")
            assert result is False


class TestSyncPull:
    @pytest.mark.asyncio
    async def test_pull_success(self):
        """Returns downloaded file path on success."""
        with (
            patch(
                "wet_mcp.sync._get_valid_token",
                return_value={"access_token": "t"},
            ),
            patch("wet_mcp.sync._find_or_create_folder", return_value="folder1"),
            patch(
                "wet_mcp.sync._find_file_in_folder",
                return_value={"id": "file1"},
            ),
            patch("wet_mcp.sync._download_file", return_value=True),
            patch("pathlib.Path.mkdir"),
            patch("pathlib.Path.exists", return_value=True),
        ):
            result = await sync.sync_pull(Path("/db/docs.db"), "wet-mcp")
            assert result is not None
            assert result.name == "remote_docs.db"

    @pytest.mark.asyncio
    async def test_pull_no_token(self):
        """Returns None when no token available."""
        with patch("wet_mcp.sync._get_valid_token", return_value=None):
            result = await sync.sync_pull(Path("/db/docs.db"), "wet-mcp")
            assert result is None

    @pytest.mark.asyncio
    async def test_pull_no_remote_file(self):
        """Returns None when no remote file exists."""
        with (
            patch(
                "wet_mcp.sync._get_valid_token",
                return_value={"access_token": "t"},
            ),
            patch("wet_mcp.sync._find_or_create_folder", return_value="folder1"),
            patch("wet_mcp.sync._find_file_in_folder", return_value=None),
        ):
            result = await sync.sync_pull(Path("/db/docs.db"), "wet-mcp")
            assert result is None

    @pytest.mark.asyncio
    async def test_pull_download_failure(self):
        """Returns None and cleans up on download failure."""
        with (
            patch(
                "wet_mcp.sync._get_valid_token",
                return_value={"access_token": "t"},
            ),
            patch("wet_mcp.sync._find_or_create_folder", return_value="folder1"),
            patch(
                "wet_mcp.sync._find_file_in_folder",
                return_value={"id": "file1"},
            ),
            patch("wet_mcp.sync._download_file", return_value=False),
            patch("pathlib.Path.mkdir"),
            patch("pathlib.Path.exists", return_value=False),
            patch("pathlib.Path.unlink") as mock_unlink,
        ):
            result = await sync.sync_pull(Path("/db/docs.db"), "wet-mcp")
            assert result is None
            mock_unlink.assert_called_once_with(missing_ok=True)


# -----------------------------------------------------------------------
# Auto-sync lifecycle
# -----------------------------------------------------------------------


@pytest.fixture(autouse=True)
def clean_sync_task():
    """Fixture to reset global _sync_task state before and after each test."""
    initial = sync._sync_task
    sync._sync_task = None
    yield
    if sync._sync_task and not sync._sync_task.done():
        sync._sync_task.cancel()
    sync._sync_task = initial


class TestAutoSync:
    """Consolidated tests for auto-sync management."""

    @pytest.mark.asyncio
    async def test_stop_auto_sync_no_task(self):
        sync._sync_task = None
        stop_auto_sync()
        assert sync._sync_task is None

    @pytest.mark.asyncio
    async def test_stop_auto_sync_already_done(self):
        future = asyncio.Future()
        future.set_result(None)
        sync._sync_task = cast(asyncio.Task, future)
        stop_auto_sync()
        assert sync._sync_task is future
        assert not future.cancelled()

    @pytest.mark.asyncio
    async def test_stop_auto_sync_running(self):
        future = asyncio.Future()
        sync._sync_task = cast(asyncio.Task, future)
        stop_auto_sync()
        assert sync._sync_task is None
        assert future.cancelled()

    @pytest.mark.asyncio
    async def test_start_auto_sync_disabled(self, clean_sync_task):
        db_mock = MagicMock()
        with patch("wet_mcp.sync.settings.sync_enabled", False):
            start_auto_sync(db_mock)
            assert sync._sync_task is None

    @pytest.mark.asyncio
    async def test_start_auto_sync_interval_zero(self, clean_sync_task):
        db_mock = MagicMock()
        with (
            patch("wet_mcp.sync.settings.sync_enabled", True),
            patch("wet_mcp.sync.settings.sync_interval", 0),
        ):
            start_auto_sync(db_mock)
            assert sync._sync_task is None

    @pytest.mark.asyncio
    async def test_start_auto_sync_already_running(self, clean_sync_task):
        db_mock = MagicMock()
        future = asyncio.Future()
        sync._sync_task = cast(asyncio.Task, future)

        with (
            patch("wet_mcp.sync.settings.sync_enabled", True),
            patch("wet_mcp.sync.settings.sync_interval", 10),
        ):
            start_auto_sync(db_mock)
            assert sync._sync_task is future

    @pytest.mark.asyncio
    @patch("wet_mcp.sync._auto_sync_loop")
    async def test_start_auto_sync_creates_task(self, mock_loop, clean_sync_task):
        db_mock = MagicMock()

        async def dummy_loop(*args):
            pass

        mock_loop.side_effect = dummy_loop

        with (
            patch("wet_mcp.sync.settings.sync_enabled", True),
            patch("wet_mcp.sync.settings.sync_interval", 10),
        ):
            start_auto_sync(db_mock)
            assert sync._sync_task is not None
            assert not sync._sync_task.done()

            await sync._sync_task

    @pytest.mark.asyncio
    @patch("wet_mcp.sync.sync_full", new_callable=AsyncMock)
    @patch("wet_mcp.sync.settings")
    async def test_auto_sync_loop_success(self, mock_settings, mock_sync_full):
        """Verify _auto_sync_loop runs sync_full and sleeps."""
        from wet_mcp.sync import _auto_sync_loop

        db_mock = MagicMock()
        mock_settings.sync_interval = 0.1

        # We'll use a side effect to break the infinite loop
        # and also verify it ran at least twice (initial + one loop)
        call_count = 0

        async def sync_side_effect(*args):
            nonlocal call_count
            call_count += 1
            if call_count >= 2:
                raise asyncio.CancelledError()

        mock_sync_full.side_effect = sync_side_effect

        try:
            await _auto_sync_loop(db_mock)
        except asyncio.CancelledError:
            pass

        assert call_count >= 2
        assert mock_sync_full.call_count >= 2

    @pytest.mark.asyncio
    @patch("wet_mcp.sync.sync_full", new_callable=AsyncMock)
    @patch("wet_mcp.sync.settings")
    @patch("wet_mcp.sync.logger")
    async def test_auto_sync_loop_initial_error(
        self, mock_logger, mock_settings, mock_sync_full
    ):
        """Verify _auto_sync_loop continues after initial sync error."""
        from wet_mcp.sync import _auto_sync_loop

        db_mock = MagicMock()
        mock_settings.sync_interval = 0.01

        # First call fails, second call we cancel to break loop
        mock_sync_full.side_effect = [
            Exception("Initial failed"),
            asyncio.CancelledError(),
        ]

        try:
            await _auto_sync_loop(db_mock)
        except asyncio.CancelledError:
            pass

        mock_logger.error.assert_any_call("Initial sync error: Initial failed")
        assert mock_sync_full.call_count == 2

    @pytest.mark.asyncio
    @patch("wet_mcp.sync.sync_full", new_callable=AsyncMock)
    @patch("wet_mcp.sync.settings")
    @patch("wet_mcp.sync.logger")
    async def test_auto_sync_loop_runtime_error(
        self, mock_logger, mock_settings, mock_sync_full
    ):
        """Verify _auto_sync_loop continues after runtime sync error."""
        from wet_mcp.sync import _auto_sync_loop

        db_mock = MagicMock()
        mock_settings.sync_interval = 0.01

        # Initial success, first loop error, second loop cancel
        mock_sync_full.side_effect = [
            None,
            Exception("Loop failed"),
            asyncio.CancelledError(),
        ]

        try:
            await _auto_sync_loop(db_mock)
        except asyncio.CancelledError:
            pass

        assert mock_sync_full.call_count == 3


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

    async def test_exception(self):
        token = {"access_token": "valid"}

        with (
            patch(
                "wet_mcp.sync._get_valid_token",
                new_callable=AsyncMock,
                return_value=token,
            ),
            patch(
                "wet_mcp.sync._drive_request",
                new_callable=AsyncMock,
                side_effect=Exception("Connection error"),
            ),
        ):
            assert await check_health() is False


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
