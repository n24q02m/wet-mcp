import json
import sqlite3
from unittest.mock import patch

from wet_mcp.db import DocsDB


def test_import_jsonl_batching_many_items(tmp_path):
    """Lines 922-930: Test batching in _get_existing with > 999 items."""
    db = DocsDB(tmp_path / "batch.db", embedding_dims=0)
    try:
        libraries = []
        for i in range(1010):
            libraries.append(
                {
                    "_type": "library",
                    "id": f"lib_{i}",
                    "name": f"lib_{i}",
                    "created_at": 1000.0,
                    "updated_at": 1000.0,
                }
            )
        data = "\n".join(json.dumps(lib_obj) for lib_obj in libraries)
        with patch("sqlite3.sqlite_version_info", (3, 31, 0)):
            stats = db.import_jsonl(data, mode="merge")
            assert stats["libraries"] == 1010
            stats2 = db.import_jsonl(data, mode="merge")
            assert stats2["skipped"] == 1010
    finally:
        db.close()


def test_import_jsonl_batching_large_sqlite_version(tmp_path):
    """Lines 922-930: Test batching in _get_existing with > 32766 items (simulated)."""
    db = DocsDB(tmp_path / "batch_large.db", embedding_dims=0)
    try:
        libraries = [
            {
                "_type": "library",
                "id": "l1",
                "name": "l1",
                "created_at": 1,
                "updated_at": 1,
            }
        ]
        data = json.dumps(libraries[0])
        with patch("sqlite3.sqlite_version_info", (3, 33, 0)):
            stats = db.import_jsonl(data, mode="merge")
            assert stats["libraries"] == 1
    finally:
        db.close()


def test_import_jsonl_empty_items(tmp_path):
    """Lines 918-919: items is empty in _get_existing."""
    db = DocsDB(tmp_path / "empty.db", embedding_dims=0)
    try:
        data = json.dumps(
            {
                "_type": "library",
                "id": "lib1",
                "name": "lib1",
                "created_at": 1000.0,
                "updated_at": 1000.0,
            }
        )
        stats = db.import_jsonl(data, mode="merge")
        assert stats["libraries"] == 1
        assert stats["versions"] == 0
        assert stats["chunks"] == 0
    finally:
        db.close()


def test_import_jsonl_mode_replace_no_vec(tmp_path):
    """Lines 884-894: mode='replace' without vec."""
    db = DocsDB(tmp_path / "replace.db", embedding_dims=0)
    try:
        db.upsert_library(name="lib1")
        data = json.dumps(
            {
                "_type": "library",
                "id": "lib2",
                "name": "lib2",
                "created_at": 1000.0,
                "updated_at": 1000.0,
            }
        )
        stats = db.import_jsonl(data, mode="replace")
        assert stats["libraries"] == 1
        libs = db._conn.execute("SELECT name FROM libraries").fetchall()
        assert len(libs) == 1
        assert libs[0][0] == "lib2"
    finally:
        db.close()


def test_import_jsonl_versions_and_chunks(tmp_path):
    """Import versions and chunks to cover 910-913."""
    db = DocsDB(tmp_path / "verchunk.db", embedding_dims=0)
    try:
        lib_id = "libA"
        ver_id = "verA"
        data = "\n".join(
            [
                json.dumps(
                    {
                        "_type": "library",
                        "id": lib_id,
                        "name": "libA",
                        "created_at": 1,
                        "updated_at": 1,
                    }
                ),
                json.dumps(
                    {
                        "_type": "version",
                        "id": ver_id,
                        "library_id": lib_id,
                        "version": "1.0",
                        "created_at": 1,
                    }
                ),
                json.dumps(
                    {
                        "_type": "chunk",
                        "id": "chkA",
                        "version_id": ver_id,
                        "library_id": lib_id,
                        "content": "hello",
                        "created_at": 1,
                    }
                ),
            ]
        )
        stats = db.import_jsonl(data, mode="merge")
        assert stats["libraries"] == 1
        assert stats["versions"] == 1
        assert stats["chunks"] == 1
    finally:
        db.close()
