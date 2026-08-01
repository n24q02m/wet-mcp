"""Regression tests: the bytes a sync backend uploads must contain the data.

``DocsDB`` opens SQLite with ``PRAGMA journal_mode = WAL`` (db.py), so freshly
committed rows -- and, on a young database, the schema itself -- live in the
``docs.db-wal`` sidecar, not in ``docs.db``. Both upload paths read the main
``.db`` file only, so without an explicit checkpoint the remote copy is a
valid-but-empty SQLite database (no tables, no rows).

Two independent upload paths exist and both are covered here:

* S3 operator mode: ``_s3_auto_sync_loop`` -> ``backend.push(db_path)``.
* GDrive uvx mode: ``_auto_sync_loop`` -> ``sync_full`` -> ``sync_push`` ->
  ``_upload_file`` (never routed through ``SyncBackend.push``).
"""

from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from wet_mcp.db import DocsDB

_CHUNK_COUNT = 3


def _seed_wal_db(db_path: Path) -> DocsDB:
    """Create a WAL-mode docs.db with real rows, leaving the writer open."""
    db = DocsDB(db_path, embedding_dims=0)
    lib_id = db.upsert_library("walcheck", docs_url="https://example.invalid/docs")
    ver_id = db.upsert_version(lib_id, "1.0.0")
    db.add_chunks(
        ver_id,
        lib_id,
        [{"content": f"wal checkpoint probe chunk {i}"} for i in range(_CHUNK_COUNT)],
    )

    mode = db._conn.execute("PRAGMA journal_mode").fetchone()[0]
    assert mode == "wal", f"expected WAL journal mode, got {mode!r}"
    assert db_path.with_name(db_path.name + "-wal").exists(), (
        "no -wal sidecar: this test cannot prove the bug without WAL"
    )
    return db


def _chunks_in_uploaded_bytes(payload: bytes, tmp_path: Path) -> int:
    """Open the exact bytes that were uploaded and count doc_chunks rows."""
    replica = tmp_path / "uploaded_replica.db"
    replica.write_bytes(payload)
    conn = sqlite3.connect(str(replica))
    try:
        tables = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        assert "doc_chunks" in tables, (
            f"uploaded docs.db has no doc_chunks table (tables={sorted(tables)}); "
            "the WAL was never checkpointed into the main file"
        )
        return conn.execute("SELECT COUNT(*) FROM doc_chunks").fetchone()[0]
    finally:
        conn.close()


async def test_s3_push_uploads_wal_checkpointed_bytes(monkeypatch, tmp_path) -> None:
    """The S3 auto-sync loop must hand the backend a checkpointed docs.db."""
    from wet_mcp.config import settings

    db_path = tmp_path / "docs.db"
    db = _seed_wal_db(db_path)

    uploaded: list[bytes] = []

    async def _capture_push(path: Path) -> bool:
        uploaded.append(Path(path).read_bytes())
        return True

    fake_backend = MagicMock()
    fake_backend.pull = AsyncMock(return_value=None)
    fake_backend.push = AsyncMock(side_effect=_capture_push)

    monkeypatch.setattr("wet_mcp.config.settings.sync_interval", 0.05)
    monkeypatch.setattr("wet_mcp.config.settings.sync_s3_bucket", "b")
    monkeypatch.setattr(type(settings), "get_db_path", lambda self: db_path)
    monkeypatch.setattr("wet_mcp.sync.get", lambda name: fake_backend)

    from wet_mcp.sync import _s3_auto_sync_loop

    task = asyncio.create_task(_s3_auto_sync_loop(db=db))
    try:
        for _ in range(60):
            await asyncio.sleep(0.05)
            if uploaded:
                break
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    assert uploaded, "auto-sync loop never pushed"
    assert _chunks_in_uploaded_bytes(uploaded[0], tmp_path) == _CHUNK_COUNT
    db.close()


async def test_gdrive_sync_push_uploads_wal_checkpointed_bytes(
    monkeypatch, tmp_path
) -> None:
    """The GDrive push path must upload a checkpointed docs.db too."""
    from wet_mcp.sync import gdrive

    db_path = tmp_path / "docs.db"
    db = _seed_wal_db(db_path)

    uploaded: list[bytes] = []

    async def _fake_drive_request(
        method: str,
        url: str,
        token: dict,
        *,
        params: dict | None = None,
        json_data: dict | None = None,
        content: bytes | None = None,
        headers: dict | None = None,
        timeout: float = 120.0,
    ) -> MagicMock:
        if content is not None:
            uploaded.append(content)
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {"id": "remote-file-id"}
        return response

    monkeypatch.setattr(
        gdrive, "_get_valid_token", AsyncMock(return_value={"access_token": "t"})
    )
    monkeypatch.setattr(
        gdrive, "_find_or_create_folder", AsyncMock(return_value="folder-id")
    )
    monkeypatch.setattr(
        gdrive,
        "_find_file_in_folder",
        AsyncMock(return_value={"id": "remote-file-id"}),
    )
    monkeypatch.setattr(gdrive, "_drive_request", _fake_drive_request)

    assert await gdrive.sync_push(db_path, "wet-mcp") is True

    assert uploaded, "sync_push never uploaded content"
    assert _chunks_in_uploaded_bytes(uploaded[0], tmp_path) == _CHUNK_COUNT
    db.close()
