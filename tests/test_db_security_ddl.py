from unittest.mock import patch

from wet_mcp.db import DocsDB


def test_create_vector_table_sql_content(tmp_path):
    db_path = tmp_path / "test_vec_sql.db"

    # We patch sqlite3.connect in the db module
    with patch("sqlite3.connect") as mock_connect:
        mock_conn = mock_connect.return_value
        # Mock fetchone for the table existence check
        mock_conn.execute.return_value.fetchone.return_value = None

        # Instantiate DocsDB with embedding_dims > 0
        # We also need to mock sqlite_vec loading to ensure _vec_enabled can be True
        with patch("importlib.import_module"):
            # DocsDB.__init__ calls _create_vector_table
            db = DocsDB(db_path, embedding_dims=1536)

            # Find the CREATE VIRTUAL TABLE call
            calls = [call.args[0] for call in mock_conn.execute.call_args_list]
            vec_calls = [c for c in calls if "CREATE VIRTUAL TABLE doc_chunks_vec" in c]

            # It might be 0 if _vec_enabled was False during init
            # Let's force it and call it again
            db._vec_enabled = True
            db._create_vector_table()

            calls = [call.args[0] for call in mock_conn.execute.call_args_list]
            vec_calls = [c for c in calls if "CREATE VIRTUAL TABLE doc_chunks_vec" in c]

            assert len(vec_calls) >= 1
            assert "embedding float[1536]" in vec_calls[0]
            assert "int(" not in vec_calls[0]


def test_alter_table_migration_loops(tmp_path):
    db_path = tmp_path / "test_alter_sql.db"

    with patch("sqlite3.connect") as mock_connect:
        mock_conn = mock_connect.return_value

        # Instantiate DocsDB
        _ = DocsDB(db_path)

        # Verify ALTER TABLE calls in _create_libraries_table
        # This is called during __init__ -> _create_libraries_table
        calls = [call.args[0] for call in mock_conn.execute.call_args_list]

        lib_alters = [
            c for c in calls if c.startswith("ALTER TABLE libraries ADD COLUMN")
        ]
        assert len(lib_alters) == 8
        assert (
            "ALTER TABLE libraries ADD COLUMN discovery_version INTEGER DEFAULT 0"
            in lib_alters
        )

        # Verify ALTER TABLE calls in _create_versions_table
        ver_alters = [
            c for c in calls if c.startswith("ALTER TABLE versions ADD COLUMN")
        ]
        assert len(ver_alters) == 2
        assert "ALTER TABLE versions ADD COLUMN release_date REAL" in ver_alters

        # Verify ALTER TABLE calls in _create_doc_chunks_table
        chunk_alters = [
            c for c in calls if c.startswith("ALTER TABLE doc_chunks ADD COLUMN")
        ]
        assert len(chunk_alters) == 4
        assert "ALTER TABLE doc_chunks ADD COLUMN section TEXT" in chunk_alters
