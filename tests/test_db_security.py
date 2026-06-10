import pytest

from wet_mcp.db import DocsDB


def test_db_initialization_with_vector_dims(tmp_path):
    db_path = tmp_path / "test.db"
    # Try with 768 dims
    db = DocsDB(db_path, embedding_dims=768)

    # Check if doc_chunks_vec table exists and has correct schema if vec is enabled
    if db._vec_enabled:
        row = db._conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='doc_chunks_vec'"
        ).fetchone()
        assert row is not None
        assert "embedding float[768]" in row["sql"]


def test_db_doc_chunks_schema(tmp_path):
    db_path = tmp_path / "test.db"
    db = DocsDB(db_path)

    # Check columns in doc_chunks
    cursor = db._conn.execute("PRAGMA table_info(doc_chunks)")
    columns = {row["name"] for row in cursor.fetchall()}

    assert "summary" in columns
    assert "summary_provider" in columns
    assert "content_hash" in columns
    assert "token_count" in columns


def test_db_libraries_schema(tmp_path):
    db_path = tmp_path / "test.db"
    db = DocsDB(db_path)

    # Check columns in libraries
    cursor = db._conn.execute("PRAGMA table_info(libraries)")
    columns = {row["name"] for row in cursor.fetchall()}

    assert "discovery_version" in columns
    assert "tier" in columns
    assert "canonical_name" in columns


def test_db_versions_schema(tmp_path):
    db_path = tmp_path / "test.db"
    db = DocsDB(db_path)

    # Check columns in versions
    cursor = db._conn.execute("PRAGMA table_info(versions)")
    columns = {row["name"] for row in cursor.fetchall()}

    assert "release_date" in columns
    assert "source_url" in columns


def test_db_invalid_dims(tmp_path):
    db_path = tmp_path / "test.db"
    with pytest.raises(ValueError, match="embedding_dims must be an integer"):
        DocsDB(db_path, embedding_dims=-1)
    with pytest.raises(ValueError, match="embedding_dims must be an integer"):
        DocsDB(db_path, embedding_dims=70000)
    with pytest.raises(ValueError, match="embedding_dims must be an integer"):
        DocsDB(db_path, embedding_dims="768")
