import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from wet_mcp import sync
from wet_mcp.sync import (
    _auto_sync_loop,
    _folder_id_cache,
    _load_token,
    _refresh_token,
    _save_token,
    setup_google_auth,
    start_auto_sync,
    stop_auto_sync,
    sync_full,
)


@pytest.fixture(autouse=True)
def clean_state():
    initial_task = sync._sync_task
    sync._sync_task = None
    _folder_id_cache.clear()
    yield
    if sync._sync_task and not sync._sync_task.done():
        sync._sync_task.cancel()
    sync._sync_task = initial_task
    _folder_id_cache.clear()


class TestSyncCoverage:
    @pytest.mark.asyncio
    async def test_sync_full_comprehensive(self, tmp_path):
        db_mock = MagicMock()
        with patch("wet_mcp.sync.settings") as ms:
            ms.sync_enabled = False
            assert (await sync_full(db_mock))["status"] == "disabled"
            ms.sync_enabled = True
            ms.google_drive_client_id = ""
            assert (await sync_full(db_mock))["status"] == "error"
            ms.google_drive_client_id = "c"
            with patch("wet_mcp.sync._has_token_available", return_value=False):
                assert (await sync_full(db_mock))["status"] == "error"
        td = tmp_path / "st"
        td.mkdir()
        rdb = td / "r.db"
        rdb.touch()
        with (
            patch("wet_mcp.sync.settings") as ms,
            patch("wet_mcp.sync._has_token_available", return_value=True),
            patch("wet_mcp.sync._get_valid_token", return_value={"access_token": "t"}),
            patch("wet_mcp.sync.sync_pull", return_value=rdb),
            patch("wet_mcp.sync.sync_push", return_value=True),
            patch("wet_mcp.db.DocsDB") as mdb_cls,
        ):
            ms.sync_enabled = True
            ms.google_drive_client_id = "c"
            ms.get_db_path.return_value = Path("db")
            mdb_cls.return_value.export_jsonl.return_value = '{"t":"l"}'
            db_mock.import_jsonl.return_value = {"ok": True}
            assert (await sync_full(db_mock))["status"] == "ok"
            assert not td.exists()

    @pytest.mark.asyncio
    async def test_auto_sync_loop_comprehensive(self):
        db_mock = MagicMock()
        with (
            patch("wet_mcp.sync.settings") as ms,
            patch(
                "wet_mcp.sync.sync_full",
                side_effect=[Exception("e1"), Exception("e2"), None],
            ),
            patch(
                "wet_mcp.sync.asyncio.sleep",
                side_effect=[None, None, asyncio.CancelledError()],
            ),
        ):
            ms.sync_interval = 0.01
            await _auto_sync_loop(db_mock)

    def test_token_internal(self):
        with patch("wet_mcp.token_store.load_token", return_value={"a": 1}):
            assert _load_token() == {"a": 1}
        with patch("wet_mcp.token_store.save_token") as m:
            _save_token({"b": 2})
            m.assert_called()

    @pytest.mark.asyncio
    async def test_refresh_token_comprehensive(self):
        with patch("wet_mcp.sync.httpx.AsyncClient") as mc:
            r = MagicMock()
            r.status_code = 200
            r.json.return_value = {"access_token": "n", "expires_in": 3600}
            mc.return_value.__aenter__.return_value.post = AsyncMock(return_value=r)
            with patch("wet_mcp.sync._save_token"):
                upd = await _refresh_token(
                    {"access_token": "o", "refresh_token": "r", "client_id": "c"}
                )
                assert upd is not None
                assert upd["refresh_token"] == "r"
            mc.return_value.__aenter__.return_value.post = AsyncMock(
                side_effect=Exception("fail")
            )
            assert (
                await _refresh_token(
                    {"access_token": "o", "refresh_token": "r", "client_id": "c"}
                )
                is None
            )

    @pytest.mark.asyncio
    async def test_auth_comprehensive(self):
        with patch("wet_mcp.sync.settings") as ms:
            ms.google_drive_client_id = "c"
            ms.google_drive_client_secret = ""
            assert await setup_google_auth() is False
        r1 = MagicMock()
        r1.status_code = 200
        r1.json.return_value = {
            "device_code": "d",
            "user_code": "u",
            "verification_url": "v",
            "interval": 0.001,
            "expires_in": 100,
        }
        p1 = MagicMock()
        p1.status_code = 400
        p1.json.return_value = {"error": "authorization_pending"}
        p2 = MagicMock()
        p2.status_code = 400
        p2.json.return_value = {"error": "slow_down"}
        p3 = MagicMock()
        p3.status_code = 400
        p3.json.return_value = {"error": "access_denied"}
        with (
            patch("wet_mcp.sync.settings") as ms,
            patch("wet_mcp.sync.httpx.AsyncClient") as mc,
            patch("wet_mcp.sync.asyncio.sleep"),
        ):
            ms.google_drive_client_id = "c"
            ms.google_drive_client_secret = "s"
            mc.return_value.__aenter__.return_value.post = AsyncMock(
                side_effect=[r1, p1, p2, p3]
            )
            assert await setup_google_auth() is False

    @pytest.mark.asyncio
    async def test_folder_comprehensive(self):
        _folder_id_cache["f"] = "m"
        with patch(
            "wet_mcp.sync._verify_folder_exists",
            new_callable=AsyncMock,
            return_value=True,
        ):
            assert await sync._find_or_create_folder({"access_token": "t"}, "f") == "m"
        _folder_id_cache.clear()
        with (
            patch("wet_mcp.sync._load_folder_id", return_value="d"),
            patch(
                "wet_mcp.sync._verify_folder_exists",
                new_callable=AsyncMock,
                return_value=True,
            ),
        ):
            assert await sync._find_or_create_folder({"access_token": "t"}, "f") == "d"

    @pytest.mark.asyncio
    async def test_start_stop(self):
        db_mock = MagicMock()
        with (
            patch("wet_mcp.sync.settings") as ms,
            patch("wet_mcp.sync.sync_full", new_callable=AsyncMock),
        ):
            ms.sync_enabled = True
            ms.sync_interval = 0.01
            start_auto_sync(db_mock)
            assert sync._sync_task is not None
            await asyncio.sleep(0.02)
            stop_auto_sync()
            assert sync._sync_task is None

    @pytest.mark.asyncio
    async def test_sync_ops_fail(self):
        with (
            patch("wet_mcp.sync._get_valid_token", return_value={"access_token": "t"}),
            patch("wet_mcp.sync._find_or_create_folder", return_value="f1"),
            patch("wet_mcp.sync._find_file_in_folder", return_value=None),
            patch("wet_mcp.sync._upload_file", return_value=False),
        ):
            assert await sync.sync_push(Path("db.db"), "folder") is False

    @pytest.mark.asyncio
    async def test_auth_relay(self):
        r1 = MagicMock()
        r1.status_code = 200
        r1.json.return_value = {
            "device_code": "d",
            "user_code": "u",
            "verification_url": "v",
            "interval": 0.001,
            "expires_in": 100,
        }
        with (
            patch("wet_mcp.sync.settings") as ms,
            patch("wet_mcp.sync.httpx.AsyncClient") as mc,
            patch("wet_mcp.sync.asyncio.sleep"),
            patch("wet_mcp.sync.time.time", side_effect=[100, 2000]),
        ):
            ms.google_drive_client_id = "c"
            ms.google_drive_client_secret = "s"
            mc.return_value.__aenter__.return_value.post = AsyncMock()
            mc.return_value.__aenter__.return_value.post.side_effect = [
                r1,
                MagicMock(status_code=200),
                MagicMock(status_code=400, json=lambda: {"error": "access_denied"}),
            ]
            assert (
                await setup_google_auth(relay_url="http://r", session_id="s") is False
            )
