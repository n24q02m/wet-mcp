"""Comprehensive tests for wet_mcp.sync -- Google Drive sync.

Covers token management, Drive API helpers, push/pull operations,
sync_full flow, auto-sync loop, setup_sync CLI, and check_health.
"""

import asyncio
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import wet_mcp.sync
from wet_mcp.sync import (
    _auto_sync_loop,
    _has_token_available,
    check_health,
    setup_sync,
    start_auto_sync,
    stop_auto_sync,
    sync_full,
    sync_pull,
    sync_push,
)


@pytest.fixture
def mock_settings():
    with patch("wet_mcp.sync.settings") as mock_settings:
        mock_settings.get_data_dir.return_value = Path("/mock/data/dir")
        mock_settings.get_db_path.return_value = Path("/mock/data/dir/db.sqlite")
        mock_settings.sync_enabled = True
        mock_settings.sync_folder = "wet_sync"
        mock_settings.sync_interval = 60
        mock_settings.google_drive_client_id = "test_client_id"
        yield mock_settings


# ---------------------------------------------------------------------------
# Token management
# ---------------------------------------------------------------------------


class TestTokenManagement:
    def test_has_token_true(self):
        with patch("wet_mcp.sync._load_token", return_value={"access_token": "x"}):
            assert _has_token_available() is True

    def test_has_token_false(self):
        with patch("wet_mcp.sync._load_token", return_value=None):
            assert _has_token_available() is False

    @pytest.mark.asyncio
    async def test_refresh_token_success(self):
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
            "expires_in": 3600,
            "token_type": "Bearer",
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
        assert result["access_token"] == "new"
        assert result["refresh_token"] == "refresh123"

    @pytest.mark.asyncio
    async def test_refresh_token_failure(self):
        from wet_mcp.sync import _refresh_token

        token = {
            "access_token": "old",
            "refresh_token": "r",
            "client_id": "c",
        }
        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_response.text = "unauthorized"

        with patch("wet_mcp.sync.httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.post = AsyncMock(return_value=mock_response)
            mock_client.return_value.__aenter__ = AsyncMock(return_value=mock_instance)
            mock_client.return_value.__aexit__ = AsyncMock(return_value=None)
            result = await _refresh_token(token)

        assert result is None

    @pytest.mark.asyncio
    async def test_refresh_token_no_refresh(self):
        from wet_mcp.sync import _refresh_token

        result = await _refresh_token({"access_token": "old"})
        assert result is None

    @pytest.mark.asyncio
    async def test_refresh_token_network_error(self):
        from wet_mcp.sync import _refresh_token

        token = {
            "access_token": "old",
            "refresh_token": "r",
            "client_id": "c",
        }

        with patch("wet_mcp.sync.httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.post = AsyncMock(side_effect=Exception("Network error"))
            mock_client.return_value.__aenter__ = AsyncMock(return_value=mock_instance)
            mock_client.return_value.__aexit__ = AsyncMock(return_value=None)
            result = await _refresh_token(token)

        assert result is None

    @pytest.mark.asyncio
    async def test_get_valid_token_fresh(self):
        from wet_mcp.sync import _get_valid_token

        token = {"access_token": "fresh", "expiry": time.time() + 3600}
        with patch("wet_mcp.sync._load_token", return_value=token):
            result = await _get_valid_token()
        assert result == token

    @pytest.mark.asyncio
    async def test_get_valid_token_expired(self):
        from wet_mcp.sync import _get_valid_token

        old = {
            "access_token": "expired",
            "expiry": time.time() - 100,
            "refresh_token": "r",
        }
        new = {"access_token": "new", "expiry": time.time() + 3600}
        with (
            patch("wet_mcp.sync._load_token", return_value=old),
            patch("wet_mcp.sync._refresh_token", return_value=new),
        ):
            result = await _get_valid_token()
        assert result == new

    @pytest.mark.asyncio
    async def test_get_valid_token_none(self):
        from wet_mcp.sync import _get_valid_token

        with patch("wet_mcp.sync._load_token", return_value=None):
            result = await _get_valid_token()
        assert result is None


# ---------------------------------------------------------------------------
# Drive API helpers
# ---------------------------------------------------------------------------


class TestDriveHelpers:
    @pytest.mark.asyncio
    async def test_find_or_create_folder_exists(self):
        from wet_mcp.sync import _find_or_create_folder

        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {"files": [{"id": "f1", "name": "sync"}]}

        with patch("wet_mcp.sync._drive_request", return_value=resp):
            result = await _find_or_create_folder({"access_token": "t"}, "sync")
        assert result == "f1"

    @pytest.mark.asyncio
    async def test_find_or_create_folder_creates(self):
        from wet_mcp.sync import _find_or_create_folder

        search_resp = MagicMock()
        search_resp.status_code = 200
        search_resp.json.return_value = {"files": []}

        create_resp = MagicMock()
        create_resp.status_code = 200
        create_resp.json.return_value = {"id": "new_f"}

        with patch(
            "wet_mcp.sync._drive_request",
            side_effect=[search_resp, create_resp],
        ):
            result = await _find_or_create_folder({"access_token": "t"}, "sync")
        assert result == "new_f"

    @pytest.mark.asyncio
    async def test_find_file_found(self):
        from wet_mcp.sync import _find_file_in_folder

        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {"files": [{"id": "file1"}]}

        with patch("wet_mcp.sync._drive_request", return_value=resp):
            result = await _find_file_in_folder({"access_token": "t"}, "f1", "docs.db")
        assert result == {"id": "file1"}

    @pytest.mark.asyncio
    async def test_find_file_not_found(self):
        from wet_mcp.sync import _find_file_in_folder

        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {"files": []}

        with patch("wet_mcp.sync._drive_request", return_value=resp):
            result = await _find_file_in_folder({"access_token": "t"}, "f1", "docs.db")
        assert result is None

    @pytest.mark.asyncio
    async def test_upload_update(self):
        from wet_mcp.sync import _upload_file

        resp = MagicMock()
        resp.status_code = 200

        with (
            patch("wet_mcp.sync._drive_request", return_value=resp),
            patch("wet_mcp.sync.asyncio.to_thread", return_value=b"data"),
        ):
            result = await _upload_file(
                {"access_token": "t"}, Path("/db.db"), "f1", "existing"
            )
        assert result is True

    @pytest.mark.asyncio
    async def test_upload_create(self):
        from wet_mcp.sync import _upload_file

        resp = MagicMock()
        resp.status_code = 201

        with (
            patch("wet_mcp.sync._drive_request", return_value=resp),
            patch("wet_mcp.sync.asyncio.to_thread", return_value=b"data"),
        ):
            result = await _upload_file(
                {"access_token": "t"}, Path("/db.db"), "f1", None
            )
        assert result is True

    @pytest.mark.asyncio
    async def test_upload_fail(self):
        from wet_mcp.sync import _upload_file

        resp = MagicMock()
        resp.status_code = 500
        resp.text = "error"

        with (
            patch("wet_mcp.sync._drive_request", return_value=resp),
            patch("wet_mcp.sync.asyncio.to_thread", return_value=b"data"),
        ):
            result = await _upload_file(
                {"access_token": "t"}, Path("/db.db"), "f1", "existing"
            )
        assert result is False

    @pytest.mark.asyncio
    async def test_download_success(self):
        from wet_mcp.sync import _download_file

        resp = MagicMock()
        resp.status_code = 200
        resp.content = b"content"

        with (
            patch("wet_mcp.sync._drive_request", return_value=resp),
            patch("wet_mcp.sync.asyncio.to_thread"),
            patch("pathlib.Path.mkdir"),
        ):
            result = await _download_file(
                {"access_token": "t"}, "file1", Path("/out.db")
            )
        assert result is True

    @pytest.mark.asyncio
    async def test_download_fail(self):
        from wet_mcp.sync import _download_file

        resp = MagicMock()
        resp.status_code = 404
        resp.text = "not found"

        with patch("wet_mcp.sync._drive_request", return_value=resp):
            result = await _download_file(
                {"access_token": "t"}, "file1", Path("/out.db")
            )
        assert result is False


# ---------------------------------------------------------------------------
# sync_push / sync_pull
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sync_push_success():
    with (
        patch("wet_mcp.sync._get_valid_token", return_value={"access_token": "t"}),
        patch("wet_mcp.sync._find_or_create_folder", return_value="f1"),
        patch("wet_mcp.sync._find_file_in_folder", return_value={"id": "e1"}),
        patch("wet_mcp.sync._upload_file", return_value=True),
    ):
        assert await sync_push(Path("/db.db"), "folder") is True


@pytest.mark.asyncio
async def test_sync_push_no_token():
    with patch("wet_mcp.sync._get_valid_token", return_value=None):
        assert await sync_push(Path("/db.db"), "folder") is False


@pytest.mark.asyncio
async def test_sync_push_no_folder():
    with (
        patch("wet_mcp.sync._get_valid_token", return_value={"access_token": "t"}),
        patch("wet_mcp.sync._find_or_create_folder", return_value=None),
    ):
        assert await sync_push(Path("/db.db"), "folder") is False


@pytest.mark.asyncio
async def test_sync_pull_success():
    with (
        patch("wet_mcp.sync._get_valid_token", return_value={"access_token": "t"}),
        patch("wet_mcp.sync._find_or_create_folder", return_value="f1"),
        patch("wet_mcp.sync._find_file_in_folder", return_value={"id": "file1"}),
        patch("wet_mcp.sync._download_file", return_value=True),
        patch("pathlib.Path.mkdir"),
        patch("pathlib.Path.exists", return_value=True),
    ):
        result = await sync_pull(Path("/db/db.sqlite"), "folder")
        assert result is not None
        assert "remote_" in result.name


@pytest.mark.asyncio
async def test_sync_pull_no_token():
    with patch("wet_mcp.sync._get_valid_token", return_value=None):
        assert await sync_pull(Path("/db.db"), "folder") is None


@pytest.mark.asyncio
async def test_sync_pull_no_file():
    with (
        patch("wet_mcp.sync._get_valid_token", return_value={"access_token": "t"}),
        patch("wet_mcp.sync._find_or_create_folder", return_value="f1"),
        patch("wet_mcp.sync._find_file_in_folder", return_value=None),
    ):
        assert await sync_pull(Path("/db.db"), "folder") is None


@pytest.mark.asyncio
async def test_sync_pull_download_fail():
    with (
        patch("wet_mcp.sync._get_valid_token", return_value={"access_token": "t"}),
        patch("wet_mcp.sync._find_or_create_folder", return_value="f1"),
        patch("wet_mcp.sync._find_file_in_folder", return_value={"id": "file1"}),
        patch("wet_mcp.sync._download_file", return_value=False),
        patch("pathlib.Path.mkdir"),
        patch("pathlib.Path.exists", return_value=False),
        patch("pathlib.Path.unlink"),
    ):
        assert await sync_pull(Path("/db.db"), "folder") is None


# ---------------------------------------------------------------------------
# sync_full
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sync_full_disabled(mock_settings):
    mock_settings.sync_enabled = False
    res = await sync_full(MagicMock())
    assert res["status"] == "disabled"


@pytest.mark.asyncio
async def test_sync_full_no_client_id(mock_settings):
    mock_settings.google_drive_client_id = ""
    res = await sync_full(MagicMock())
    assert res["status"] == "error"
    assert "GOOGLE_DRIVE_CLIENT_ID" in res["message"]


@pytest.mark.asyncio
@patch("wet_mcp.sync._has_token_available", return_value=False)
async def test_sync_full_no_token(_mock_token, mock_settings):
    res = await sync_full(MagicMock())
    assert res["status"] == "error"
    assert "token" in res["message"].lower()


@pytest.mark.asyncio
@patch("wet_mcp.sync._has_token_available", return_value=True)
@patch("wet_mcp.sync._get_valid_token", return_value=None)
async def test_sync_full_token_refresh_fails(_mock_valid, _mock_has, mock_settings):
    res = await sync_full(MagicMock())
    assert res["status"] == "error"
    assert "expired" in res["message"].lower()


@pytest.mark.asyncio
@patch("wet_mcp.sync._has_token_available", return_value=True)
@patch("wet_mcp.sync._get_valid_token")
@patch("wet_mcp.sync.sync_pull")
@patch("wet_mcp.sync.sync_push")
@patch("wet_mcp.db.DocsDB")
async def test_sync_full_success(
    mock_DocsDB, mock_push, mock_pull, mock_valid, _mock_has, mock_settings
):
    mock_valid.return_value = {"access_token": "t"}
    mock_pull.return_value = Path("/tmp/remote.sqlite")
    mock_push.return_value = True

    mock_remote_db = MagicMock()
    mock_remote_db.export_jsonl.return_value = '{"id":"test"}'
    mock_DocsDB.return_value = mock_remote_db

    mock_local_db = MagicMock()
    mock_local_db.import_jsonl.return_value = {"libraries": 1}

    res = await sync_full(mock_local_db)
    assert res["status"] == "ok"
    assert res["pull"] == {"libraries": 1}
    assert res["push"]["success"] is True


@pytest.mark.asyncio
@patch("wet_mcp.sync._has_token_available", return_value=True)
@patch("wet_mcp.sync._get_valid_token")
@patch("wet_mcp.sync.sync_pull", return_value=None)
@patch("wet_mcp.sync.sync_push", return_value=True)
async def test_sync_full_no_remote(
    mock_push, mock_pull, mock_valid, _mock_has, mock_settings
):
    mock_valid.return_value = {"access_token": "t"}
    res = await sync_full(MagicMock())
    assert res["status"] == "ok"
    assert res["pull"]["note"] == "No remote DB found"


@pytest.mark.asyncio
@patch("wet_mcp.sync._has_token_available", return_value=True)
@patch("wet_mcp.sync._get_valid_token")
@patch("wet_mcp.sync.sync_pull")
@patch("wet_mcp.sync.sync_push", return_value=True)
@patch("wet_mcp.db.DocsDB")
async def test_sync_full_merge_error(
    mock_DocsDB, mock_push, mock_pull, mock_valid, _mock_has, mock_settings
):
    mock_valid.return_value = {"access_token": "t"}
    mock_pull.return_value = Path("/tmp/remote.sqlite")
    mock_DocsDB.side_effect = Exception("DB Error")

    res = await sync_full(MagicMock())
    assert res["status"] == "ok"
    assert "error" in res["pull"]


# ---------------------------------------------------------------------------
# Auto-sync loop & lifecycle
# ---------------------------------------------------------------------------


@patch("wet_mcp.sync.settings")
@patch("wet_mcp.sync.asyncio.sleep")
@patch("wet_mcp.sync.sync_full")
@pytest.mark.asyncio
async def test_auto_sync_loop_cancel(mock_sync, mock_sleep, mock_settings):
    mock_settings.sync_interval = 60
    mock_sleep.side_effect = asyncio.CancelledError()
    await _auto_sync_loop(MagicMock())
    assert mock_sync.await_count == 1


@patch("wet_mcp.sync.settings")
@pytest.mark.asyncio
async def test_auto_sync_loop_disabled(mock_settings):
    mock_settings.sync_interval = 0
    await _auto_sync_loop(MagicMock())


@patch("wet_mcp.sync.settings")
@patch("wet_mcp.sync.asyncio.create_task")
def test_start_auto_sync(mock_create, mock_settings):
    mock_settings.sync_enabled = True
    mock_settings.sync_interval = 60
    wet_mcp.sync._sync_task = None
    start_auto_sync(MagicMock())
    mock_create.assert_called_once()

    # Should not create again when already running
    mock_create.reset_mock()
    wet_mcp.sync._sync_task = MagicMock()
    wet_mcp.sync._sync_task.done.return_value = False
    start_auto_sync(MagicMock())
    mock_create.assert_not_called()


def test_stop_auto_sync():
    mock_task = MagicMock()
    mock_task.done.return_value = False
    wet_mcp.sync._sync_task = mock_task
    stop_auto_sync()
    mock_task.cancel.assert_called_once()
    assert wet_mcp.sync._sync_task is None


# ---------------------------------------------------------------------------
# check_health
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_check_health_success():
    resp = MagicMock()
    resp.status_code = 200

    with (
        patch("wet_mcp.sync._get_valid_token", return_value={"access_token": "t"}),
        patch("wet_mcp.sync._drive_request", return_value=resp),
    ):
        assert await check_health() is True


@pytest.mark.asyncio
async def test_check_health_no_token():
    with patch("wet_mcp.sync._get_valid_token", return_value=None):
        assert await check_health() is False


@pytest.mark.asyncio
async def test_check_health_error():
    with (
        patch("wet_mcp.sync._get_valid_token", return_value={"access_token": "t"}),
        patch("wet_mcp.sync._drive_request", side_effect=Exception("err")),
    ):
        assert await check_health() is False


# ---------------------------------------------------------------------------
# setup_sync CLI
# ---------------------------------------------------------------------------


@patch("wet_mcp.sync.settings")
@patch("wet_mcp.sync.setup_google_auth")
def test_setup_sync_success(mock_auth, mock_settings, capsys):
    mock_settings.google_drive_client_id = "test_client_id"
    mock_auth.return_value = True

    with patch("wet_mcp.sync.asyncio.run", return_value=True):
        setup_sync()

    captured = capsys.readouterr()
    assert "SUCCESS" in captured.out
    assert "SYNC_ENABLED" in captured.out


@patch("wet_mcp.sync.settings")
def test_setup_sync_no_client_id(mock_settings):
    mock_settings.google_drive_client_id = ""

    with pytest.raises(SystemExit):
        setup_sync()


@patch("wet_mcp.sync.settings")
def test_setup_sync_auth_fails(mock_settings):
    mock_settings.google_drive_client_id = "test_client_id"

    with (
        patch("wet_mcp.sync.asyncio.run", return_value=False),
        pytest.raises(SystemExit),
    ):
        setup_sync()


# ---------------------------------------------------------------------------
# setup_google_auth (Device Code flow)
# ---------------------------------------------------------------------------


class TestSetupGoogleAuth:
    @pytest.mark.asyncio
    async def test_no_client_id(self):
        from wet_mcp.sync import setup_google_auth

        with patch("wet_mcp.sync.settings.google_drive_client_id", ""):
            assert await setup_google_auth() is False

    @pytest.mark.asyncio
    async def test_device_code_request_fails(self):
        from wet_mcp.sync import setup_google_auth

        resp = MagicMock()
        resp.status_code = 400
        resp.text = "bad request"

        with (
            patch("wet_mcp.sync.settings.google_drive_client_id", "client123"),
            patch("wet_mcp.sync.httpx.AsyncClient") as mock_client,
        ):
            mock_instance = AsyncMock()
            mock_instance.post = AsyncMock(return_value=resp)
            mock_client.return_value.__aenter__ = AsyncMock(return_value=mock_instance)
            mock_client.return_value.__aexit__ = AsyncMock(return_value=None)
            assert await setup_google_auth() is False

    @pytest.mark.asyncio
    async def test_device_code_network_error(self):
        from wet_mcp.sync import setup_google_auth

        with (
            patch("wet_mcp.sync.settings.google_drive_client_id", "client123"),
            patch("wet_mcp.sync.httpx.AsyncClient") as mock_client,
        ):
            mock_instance = AsyncMock()
            mock_instance.post = AsyncMock(side_effect=Exception("Network error"))
            mock_client.return_value.__aenter__ = AsyncMock(return_value=mock_instance)
            mock_client.return_value.__aexit__ = AsyncMock(return_value=None)
            assert await setup_google_auth() is False
