from unittest.mock import MagicMock, patch

import pytest

from wet_mcp.db import DocsDB


def test_get_table_columns_caching(tmp_path):
    db_path = tmp_path / "test.db"
    db = DocsDB(db_path)

    # We can't mock sqlite3.Connection.execute directly because it's read-only.
    # Instead, we mock _get_table_columns if we want to test its usage,
    # but here we want to test that _get_table_columns itself caches.

    # Let's patch the connection object entirely or use a simpler approach.
    with patch.object(db, "_conn") as mock_conn:
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [{"name": "id"}, {"name": "name"}]
        mock_conn.execute.return_value = mock_cursor

        # First call
        cols1 = db._get_table_columns("libraries")
        assert "id" in cols1
        assert mock_conn.execute.call_count == 1

        # Second call
        cols2 = db._get_table_columns("libraries")
        assert cols1 == cols2
        # call_count should still be 1 if cached
        assert mock_conn.execute.call_count == 1


def test_get_table_columns_invalid_table(tmp_path):
    db = DocsDB(tmp_path / "test.db")
    with pytest.raises(ValueError, match="Invalid table for column lookup"):
        db._get_table_columns("non_existent_table")


def test_get_table_columns_doc_chunks(tmp_path):
    db = DocsDB(tmp_path / "test.db")
    cols = db._get_table_columns("doc_chunks")
    assert "id" in cols
    assert "content" in cols
