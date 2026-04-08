import pytest
from unittest.mock import patch
from wet_mcp.db import DocsDB

@pytest.fixture
def db(tmp_path):
    db_path = tmp_path / "test.db"
    db = DocsDB(db_path)
    yield db
    db.close()

def test_get_existing_ids_invalid_table(db):
    """Test _get_existing_ids raises ValueError for unauthorized table names."""
    with pytest.raises(ValueError, match="Invalid table name"):
        db._get_existing_ids("unauthorized_table", ["123"])

def test_get_existing_ids_valid_tables(db):
    """Test _get_existing_ids works for authorized table names."""
    # Should not raise
    db._get_existing_ids("libraries", [])
    db._get_existing_ids("versions", [])
    db._get_existing_ids("doc_chunks", [])

def test_upsert_library_unauthorized_fragment(db):
    """Test upsert_library raises ValueError for unauthorized SQL fragments."""
    # First, create a library to trigger the update path
    db.upsert_library(name="testlib")

    # Mock _ALLOWED_LIBRARY_UPDATES to test the validation logic
    # We can't easily patch the constant if it's already used in the method,
    # but since it's a module level constant, we can try to patch it.
    with patch("wet_mcp.db._ALLOWED_LIBRARY_UPDATES", {"docs_url = ?"}):
        # This should pass
        db.upsert_library(name="testlib", docs_url="http://example.com")

        # This should fail because 'registry = ?' is not in our mocked set
        with pytest.raises(ValueError, match="Unauthorized update fragment"):
            db.upsert_library(name="testlib", registry="npm")

def test_import_jsonl_basic(db):
    """Test import_jsonl still works with the new refactored _get_existing_ids."""
    data = '{"_type": "library", "id": "lib1", "name": "lib1", "created_at": 100, "updated_at": 100}\n'
    data += '{"_type": "version", "id": "ver1", "library_id": "lib1", "version": "1.0", "created_at": 100}\n'

    stats = db.import_jsonl(data, mode="merge")
    assert stats["libraries"] == 1
    assert stats["versions"] == 1

    # Import again, should be skipped
    stats = db.import_jsonl(data, mode="merge")
    assert stats["libraries"] == 0
    assert stats["skipped"] >= 2
