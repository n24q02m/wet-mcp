import sqlite3
import unittest.mock
from unittest.mock import MagicMock, patch
import pytest

# Use the bootstrap logic from test_db.py to avoid crawl4ai dependency
import importlib.util
import sys
import types
from pathlib import Path

_src_root = Path(__file__).resolve().parent.parent / "src"

if "wet_mcp" not in sys.modules:
    _pkg = types.ModuleType("wet_mcp")
    _pkg.__path__ = [str(_src_root / "wet_mcp")]
    sys.modules["wet_mcp"] = _pkg

if "wet_mcp.sources" not in sys.modules:
    _sources_pkg = types.ModuleType("wet_mcp.sources")
    _sources_pkg.__path__ = [str(_src_root / "wet_mcp" / "sources")]
    sys.modules["wet_mcp.sources"] = _sources_pkg

# Load docs module
_docs_file = _src_root / "wet_mcp" / "sources" / "docs.py"
_docs_spec = importlib.util.spec_from_file_location("wet_mcp.sources.docs", _docs_file)
assert _docs_spec is not None
_docs_mod = importlib.util.module_from_spec(_docs_spec)
sys.modules["wet_mcp.sources.docs"] = _docs_mod
_docs_spec.loader.exec_module(_docs_mod)

# Load db module
_db_file = _src_root / "wet_mcp" / "db.py"
_db_spec = importlib.util.spec_from_file_location("wet_mcp.db", _db_file)
assert _db_spec is not None
_db_mod = importlib.util.module_from_spec(_db_spec)
sys.modules["wet_mcp.db"] = _db_mod
_db_spec.loader.exec_module(_db_mod)

DocsDB = _db_mod.DocsDB

@pytest.fixture
def db(tmp_path):
    return DocsDB(tmp_path / "test_err.db", embedding_dims=0)

class TestDbErrorPaths:
    def test_clear_version_chunks_vector_error_handled(self, db):
        """Line 548-551: clear_version_chunks handles error in vector delete."""
        db._vec_enabled = True

        # We can't patch sqlite3.Connection methods directly as they are read-only.
        # Instead, we can mock the entire connection or use a wrapper.
        real_conn = db._conn
        mock_conn = MagicMock(wraps=real_conn)

        def mocked_execute(sql, *args):
            if "DELETE FROM doc_chunks_vec" in sql:
                raise sqlite3.OperationalError("Mocked vector delete failure")
            return real_conn.execute(sql, *args)

        mock_conn.execute.side_effect = mocked_execute
        db._conn = mock_conn

        # This should not raise, but log a warning.
        db.clear_version_chunks("dummy_version")

    def test_add_chunks_batch_insert_vector_error_handled(self, db):
        """Line 531-532: add_chunks handles error in vector batch insert."""
        db._vec_enabled = True
        chunks = [{"content": "test chunk"}]
        embeddings = [[0.1] * 1536]

        real_conn = db._conn
        mock_conn = MagicMock(wraps=real_conn)

        def mocked_executemany(sql, *args):
            if "INSERT INTO doc_chunks_vec" in sql:
                raise sqlite3.OperationalError("Mocked vector insert failure")
            return real_conn.executemany(sql, *args)

        mock_conn.executemany.side_effect = mocked_executemany
        db._conn = mock_conn

        # Should not raise
        db.add_chunks("ver_id", "lib_id", chunks, embeddings=embeddings)

    def test_add_chunks_serialize_embedding_error_handled(self, db):
        """Line 523-524: add_chunks handles error in embedding serialization."""
        db._vec_enabled = True
        chunks = [{"content": "test chunk"}]
        embeddings = ["invalid"]

        with patch("wet_mcp.db._serialize_f32", side_effect=ValueError("Bad embedding")):
            db.add_chunks("ver_id", "lib_id", chunks, embeddings=embeddings)

    def test_search_fts_error_handled(self, db):
        """Line 690-692: search handles error in FTS search tiers."""
        real_conn = db._conn
        mock_conn = MagicMock(wraps=real_conn)

        def mocked_execute(sql, *args):
            if "MATCH" in sql and "doc_chunks_fts" in sql:
                raise sqlite3.OperationalError("Mocked FTS failure")
            return real_conn.execute(sql, *args)

        mock_conn.execute.side_effect = mocked_execute
        db._conn = mock_conn

        results = db.search("test")
        assert results == []

    def test_search_vector_error_handled(self, db):
        """Line 738-739: search handles error in vector search."""
        db._vec_enabled = True

        real_conn = db._conn
        mock_conn = MagicMock(wraps=real_conn)

        def mocked_execute(sql, *args):
            if "MATCH" in sql and "doc_chunks_vec" in sql:
                raise sqlite3.OperationalError("Mocked vector search failure")
            return real_conn.execute(sql, *args)

        mock_conn.execute.side_effect = mocked_execute
        db._conn = mock_conn

        results = db.search("test", query_embedding=[0.1]*1536)
        assert isinstance(results, list)

    def test_close_error_handled(self, db):
        """Line 1033-1034: close() handles error."""
        mock_conn = MagicMock()
        mock_conn.close.side_effect = Exception("Close failed")
        db._conn = mock_conn
        db.close()

    def test_vec_extension_load_error_handled(self, tmp_path):
        """Line 169-170: DocsDB handles error loading sqlite-vec."""
        with patch("sqlite_vec.load", side_effect=Exception("Load failed")):
            d = DocsDB(tmp_path / "no_vec.db", embedding_dims=1536)
            assert d._vec_enabled is False
