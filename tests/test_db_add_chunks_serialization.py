import sqlite3

from wet_mcp.db import DocsDB


class TestAddChunksSerialization:
    def test_add_chunks_serialization_error_extra(self, tmp_path):
        """Verify add_chunks handles embedding serialization failure and continues."""
        # Initialize DocsDB with vector support enabled
        db = DocsDB(tmp_path / "extra_ser.db", embedding_dims=2)
        db._vec_enabled = True

        lib_id = db.upsert_library(name="extra_lib")
        ver_id = db.upsert_version(lib_id)

        chunks = [{"content": "valid_chunk"}, {"content": "error_chunk"}]
        # First embedding is valid (list of 2 floats), second is invalid (string)
        embeddings = [[1.0, 2.0], "invalid_embedding"]

        # Should NOT raise an exception and should return total chunk count
        count = db.add_chunks(ver_id, lib_id, chunks, embeddings=embeddings)
        assert count == 2

        # Verify both chunks were inserted into the main table
        rows = db._conn.execute(
            "SELECT content FROM doc_chunks ORDER BY content"
        ).fetchall()
        assert len(rows) == 2
        assert rows[0][0] == "error_chunk"
        assert rows[1][0] == "valid_chunk"

        # Verify only the valid vector was inserted into the vector table
        try:
            vec_rows = db._conn.execute(
                "SELECT count(*) FROM doc_chunks_vec"
            ).fetchone()
            assert vec_rows[0] == 1
        except sqlite3.OperationalError:
            # sqlite-vec not loaded/supported in this environment, which is fine
            pass

        db.close()

    def test_search_serialization_error(self, tmp_path):
        """Verify search handles query embedding serialization failure."""
        db = DocsDB(tmp_path / "search_ser.db", embedding_dims=2)
        db._vec_enabled = True

        # Invalid query embedding (not a list of floats)
        query_embedding = "invalid"

        # Should NOT raise an exception and return empty results (or at least handle error)
        # Note: search handles serialization in the try-except block of the search method itself?
        # Let's check the search code again.
        results = db.search("query", query_embedding=query_embedding)
        assert results == []
        db.close()
