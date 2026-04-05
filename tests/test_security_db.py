import pytest

from wet_mcp.db import DocsDB


def test_get_existing_allowlist_enforcement(tmp_path, monkeypatch):
    import wet_mcp.db

    # To test the ValueError, we can temporarily clear the allowlist
    # and see if it raises ValueError even for "libraries"
    db = DocsDB(tmp_path / "test.db")
    try:
        # Create a test entry
        db.upsert_library("testlib")

        # Monkeypatch _ALLOWED_IMPORT_TABLES to be empty
        monkeypatch.setattr(wet_mcp.db, "_ALLOWED_IMPORT_TABLES", frozenset())

        # This should trigger _get_existing with mode="merge"
        with pytest.raises(ValueError, match="Invalid table name: libraries"):
            db.import_jsonl(
                '{"id": "1", "name": "lib1", "_type": "library"}', mode="merge"
            )

    finally:
        db.close()


def test_upsert_library_allowlist_enforcement(tmp_path, monkeypatch):
    import wet_mcp.db

    db = DocsDB(tmp_path / "test.db")
    try:
        # Create first
        db.upsert_library("testlib")

        # Mock allowlist to be empty
        monkeypatch.setattr(wet_mcp.db, "_ALLOWED_LIBRARY_UPDATES", frozenset())

        with pytest.raises(ValueError, match="Invalid update fragment"):
            db.upsert_library("testlib", description="fail")

    finally:
        db.close()


def test_upsert_library_normal_operation(tmp_path):
    """Verify that upsert_library still works normally after refactor."""
    db = DocsDB(tmp_path / "test.db")
    try:
        lib_id = db.upsert_library("testlib", description="initial")
        assert lib_id is not None

        # Update
        lib_id2 = db.upsert_library("testlib", description="updated", registry="npm")
        assert lib_id == lib_id2

        lib = db.get_library("testlib")
        assert lib["description"] == "updated"
        assert lib["registry"] == "npm"
    finally:
        db.close()


def test_import_jsonl_normal_operation(tmp_path):
    """Verify that import_jsonl still works normally after refactor."""
    db = DocsDB(tmp_path / "test.db")
    try:
        data = '{"id": "1", "name": "lib1", "created_at": 1, "updated_at": 1, "_type": "library"}'
        stats = db.import_jsonl(data, mode="merge")
        assert stats["libraries"] == 1

        lib = db.get_library("lib1")
        assert lib is not None
    finally:
        db.close()
