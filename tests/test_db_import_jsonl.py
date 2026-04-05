import json
import sqlite3
from unittest.mock import patch

import pytest

from wet_mcp.db import DocsDB


@pytest.fixture
def db_simple(tmp_path):
    db = DocsDB(tmp_path / "simple.db", embedding_dims=0)
    yield db
    db.close()


def test_get_existing_ids_invalid_table(db_simple):
    """_get_existing_ids raises ValueError for invalid table names."""
    with pytest.raises(ValueError, match="Invalid table name:"):
        db_simple._get_existing_ids("invalid_table", ["123"])


def test_get_existing_ids_empty_list(db_simple):
    """_get_existing_ids returns empty set for empty input list."""
    assert db_simple._get_existing_ids("libraries", []) == set()


def test_get_existing_ids_batching(db_simple):
    """_get_existing_ids handles batching correctly."""
    lib_id = db_simple.upsert_library(name="batchlib")
    ids = [lib_id]

    # Mock sqlite_version_info to force small batches
    with patch("sqlite3.sqlite_version_info", (3, 31, 0)):
        # batch_size will be 999
        # Let s test with 2 IDs to see it working
        ids.append("nonexistent")
        existing = db_simple._get_existing_ids("libraries", ids)
        assert existing == {lib_id}


def test_import_jsonl_full_roundtrip(tmp_path):
    """Test import_jsonl with all types and modes."""
    db_path = tmp_path / "test_round.db"
    db = DocsDB(db_path, embedding_dims=0)

    # 1. Create data
    lib_id = "lib123"
    ver_id = "ver456"
    chunk_id = "chunk789"

    data = [
        {
            "_type": "library",
            "id": lib_id,
            "name": "testlib",
            "created_at": 1.0,
            "updated_at": 1.0,
        },
        {
            "_type": "version",
            "id": ver_id,
            "library_id": lib_id,
            "version": "1.0.0",
            "created_at": 1.0,
        },
        {
            "_type": "chunk",
            "id": chunk_id,
            "version_id": ver_id,
            "library_id": lib_id,
            "content": "hello",
            "created_at": 1.0,
        },
        {"_type": "invalid", "something": "else"},  # Should be ignored
    ]
    jsonl_data = "\n".join(json.dumps(obj) for obj in data)

    # 2. Import in merge mode (clean db)
    stats = db.import_jsonl(jsonl_data, mode="merge")
    assert stats == {"libraries": 1, "versions": 1, "chunks": 1, "skipped": 0}

    # Verify data - get_library uses name
    assert db.get_library("testlib") is not None

    # 3. Import again in merge mode (should skip)
    stats = db.import_jsonl(jsonl_data, mode="merge")
    assert stats == {"libraries": 0, "versions": 0, "chunks": 0, "skipped": 3}

    # 4. Import in replace mode
    stats = db.import_jsonl(jsonl_data, mode="replace")
    assert stats == {"libraries": 1, "versions": 1, "chunks": 1, "skipped": 0}

    db.close()


def test_import_jsonl_duplicate_in_input(db_simple):
    """Test import_jsonl with duplicate IDs in the same input string."""
    lib_id = "dup_in_input"
    data = [
        {
            "_type": "library",
            "id": lib_id,
            "name": "lib1",
            "created_at": 1.0,
            "updated_at": 1.0,
        },
        {
            "_type": "library",
            "id": lib_id,
            "name": "lib2",
            "created_at": 2.0,
            "updated_at": 2.0,
        },
    ]
    jsonl_data = "\n".join(json.dumps(obj) for obj in data)

    # In merge mode, it should skip the second one if already in existing_libs set
    stats = db_simple.import_jsonl(jsonl_data, mode="merge")
    assert stats["libraries"] == 1
    assert stats["skipped"] == 1


def test_import_jsonl_replace_vec_error(tmp_path):
    """Test import_jsonl replace mode when vector table deletion fails."""
    db = DocsDB(tmp_path / "vec_err.db", embedding_dims=0)
    db._vec_enabled = True

    # Wrap connection to intercept execute
    class FailVecConn:
        def __init__(self, conn):
            self.conn = conn

        def execute(self, sql, *args):
            if "DELETE FROM doc_chunks_vec" in sql:
                raise sqlite3.OperationalError("Mocked failure")
            return self.conn.execute(sql, *args)

        def __getattr__(self, name):
            return getattr(self.conn, name)

    db._conn = FailVecConn(db._conn)

    # Should not raise, just log warning
    stats = db.import_jsonl("{}", mode="replace")
    assert stats["skipped"] == 0

    db.close()
