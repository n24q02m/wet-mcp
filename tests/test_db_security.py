from unittest.mock import MagicMock, patch

import pytest

from wet_mcp.db import DocsDB


def test_embedding_dims_validation(tmp_path):
    db_path = tmp_path / "test.db"

    # Valid dimensions
    DocsDB(db_path, embedding_dims=128)

    # Invalid dimensions - negative
    with pytest.raises(ValueError, match="embedding_dims must be an integer 0-65536"):
        DocsDB(db_path, embedding_dims=-1)

    # Invalid dimensions - too large
    with pytest.raises(ValueError, match="embedding_dims must be an integer 0-65536"):
        DocsDB(db_path, embedding_dims=70000)

    # Invalid type - string
    with pytest.raises(ValueError, match="embedding_dims must be an integer 0-65536"):
        DocsDB(db_path, embedding_dims="128")


def test_embedding_dims_casting_in_sql(tmp_path):
    db_path = tmp_path / "test.db"

    # Mock sqlite3.connect to capture the execute calls
    import sqlite3

    mock_conn = MagicMock(spec=sqlite3.Connection)
    # Ensure fetchone returns None for the table existence check
    mock_conn.execute.return_value.fetchone.return_value = None

    with patch("sqlite3.connect", return_value=mock_conn):
        # Mock sqlite-vec loading
        with patch("sqlite_vec.load"):
            # We want to verify that _create_vector_table uses int casting
            # Since it's called in __init__, we just need to instantiate DocsDB
            # and check the calls to mock_conn.execute

            db = DocsDB(db_path, embedding_dims=128)
            # Force _vec_enabled to True for the test if it wasn't already (e.g. if sqlite-vec is missing in env)
            db._vec_enabled = True
            db._create_vector_table()

            # Find the CREATE VIRTUAL TABLE call
            create_table_calls = [
                call
                for call in mock_conn.execute.call_args_list
                if "CREATE VIRTUAL TABLE doc_chunks_vec" in str(call)
            ]

            assert len(create_table_calls) > 0
            sql = create_table_calls[0][0][0]
            assert "embedding float[128]" in sql
