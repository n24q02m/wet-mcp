import pytest


@pytest.fixture
def db_mod():
    """Lazy import of the db module."""
    import wet_mcp.db as db_mod

    return db_mod


@pytest.fixture
def db(db_mod, tmp_path):
    """Fixture for a clean DocsDB instance."""
    db_instance = db_mod.DocsDB(tmp_path / "test.db")
    yield db_instance
    db_instance.close()


def test_get_existing_allowlist_enforcement(db, db_mod, monkeypatch):
    # Create a test entry
    db.upsert_library("testlib")

    # Monkeypatch _ALLOWED_IMPORT_TABLES to be empty
    monkeypatch.setattr(db_mod, "_ALLOWED_IMPORT_TABLES", frozenset())

    # This should trigger _get_existing with mode="merge"
    with pytest.raises(ValueError, match="Invalid table name: libraries"):
        db.import_jsonl('{"id": "1", "name": "lib1", "_type": "library"}', mode="merge")


def test_upsert_library_allowlist_enforcement(db, db_mod, monkeypatch):
    # Create first
    db.upsert_library("testlib")

    # Mock allowlist to be empty
    monkeypatch.setattr(db_mod, "_ALLOWED_LIBRARY_UPDATES", frozenset())

    with pytest.raises(ValueError, match="Invalid update fragment"):
        db.upsert_library("testlib", description="fail")


def test_upsert_library_normal_operation(db):
    """Verify that upsert_library still works normally after refactor."""
    lib_id = db.upsert_library("testlib", description="initial")
    assert lib_id is not None

    # Update
    lib_id2 = db.upsert_library("testlib", description="updated", registry="npm")
    assert lib_id == lib_id2

    lib = db.get_library("testlib")
    assert lib["description"] == "updated"
    assert lib["registry"] == "npm"


def test_import_jsonl_normal_operation(db):
    """Verify that import_jsonl still works normally after refactor."""
    data = '{"id": "1", "name": "lib1", "created_at": 1, "updated_at": 1, "_type": "library"}'
    stats = db.import_jsonl(data, mode="merge")
    assert stats["libraries"] == 1

    lib = db.get_library("lib1")
    assert lib is not None
