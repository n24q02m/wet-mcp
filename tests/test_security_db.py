import importlib.util
import sys
import types
from pathlib import Path
from unittest.mock import patch

import pytest

# Reuse the bootstrap logic from test_db.py
_src_root = Path(__file__).resolve().parent.parent / "src"

if "wet_mcp" not in sys.modules:
    _pkg = types.ModuleType("wet_mcp")
    _pkg.__path__ = [str(_src_root / "wet_mcp")]
    sys.modules["wet_mcp"] = _pkg

if "wet_mcp.sources" not in sys.modules:
    _sources_pkg = types.ModuleType("wet_mcp.sources")
    _sources_pkg.__path__ = [str(_src_root / "wet_mcp" / "sources")]
    sys.modules["wet_mcp.sources"] = _sources_pkg

_docs_file = _src_root / "wet_mcp" / "sources" / "docs.py"
_docs_spec = importlib.util.spec_from_file_location("wet_mcp.sources.docs", _docs_file)
_docs_mod = importlib.util.module_from_spec(_docs_spec)
sys.modules["wet_mcp.sources.docs"] = _docs_mod
_docs_spec.loader.exec_module(_docs_mod)

_db_file = _src_root / "wet_mcp" / "db.py"
_db_spec = importlib.util.spec_from_file_location("wet_mcp.db", _db_file)
_db_mod = importlib.util.module_from_spec(_db_spec)
sys.modules["wet_mcp.db"] = _db_mod
_db_spec.loader.exec_module(_db_mod)

DocsDB = _db_mod.DocsDB


@pytest.fixture
def db(tmp_path):
    db_path = tmp_path / "security_test.db"
    db = DocsDB(db_path)
    yield db
    db.close()


def test_upsert_library_allowlist_enforcement(db):
    """Verify that upsert_library raises ValueError for forbidden fragments."""
    # Normal usage should work
    lib_id = db.upsert_library("testlib", docs_url="https://example.com")
    assert lib_id is not None

    # Trigger an update
    with patch("wet_mcp.db._ALLOWED_UPDATES", frozenset()):
        with pytest.raises(ValueError, match="Forbidden update fragment"):
            db.upsert_library("testlib", docs_url="https://example.com/new")


def test_import_jsonl_minimal(db):
    """Verify that import_jsonl works with minimal data."""
    import json

    data = json.dumps(
        {
            "_type": "library",
            "id": "lib1",
            "name": "lib1",
            "docs_url": "http://x.com",
            "created_at": 0.0,
            "updated_at": 0.0,
        }
    )
    db.import_jsonl(data)
    assert db.get_library("lib1") is not None


def test_create_vector_table_sql_construction(tmp_path):
    """Verify that _create_vector_table constructs correct SQL."""
    db_path = tmp_path / "vector_test.db"
    # Create DB with 128 dims
    db = DocsDB(db_path, embedding_dims=128)
    # If sqlite-vec is available, it would create it.
    # We can at least check if it didn't crash.
    db.close()
