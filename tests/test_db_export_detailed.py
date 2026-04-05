"""Detailed tests for export_jsonl in src/wet_mcp/db.py."""

import importlib.util
import json
import sys
import types
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Bootstrap: load wet_mcp.db directly from file without triggering the
# package __init__.py (which imports crawl4ai -> numpy, a flaky dep).
# ---------------------------------------------------------------------------
_src_root = Path(__file__).resolve().parent.parent / "src"

if "wet_mcp" not in sys.modules:
    _pkg = types.ModuleType("wet_mcp")
    _pkg.__path__ = [str(_src_root / "wet_mcp")]
    sys.modules["wet_mcp"] = _pkg

if "wet_mcp.sources" not in sys.modules:
    _sources_pkg = types.ModuleType("wet_mcp.sources")
    _sources_pkg.__path__ = [str(_src_root / "wet_mcp" / "sources")]
    sys.modules["wet_mcp.sources"] = _sources_pkg

# Load docs module (lightweight — no crawl4ai dependency)
_docs_file = _src_root / "wet_mcp" / "sources" / "docs.py"
_docs_spec = importlib.util.spec_from_file_location("wet_mcp.sources.docs", _docs_file)
assert _docs_spec is not None
_docs_mod = importlib.util.module_from_spec(_docs_spec)
sys.modules["wet_mcp.sources.docs"] = _docs_mod
_docs_spec.loader.exec_module(_docs_mod)

# Now load db module
_db_file = _src_root / "wet_mcp" / "db.py"
_db_spec = importlib.util.spec_from_file_location("wet_mcp.db", _db_file)
assert _db_spec is not None
_db_mod = importlib.util.module_from_spec(_db_spec)
sys.modules["wet_mcp.db"] = _db_mod
_db_spec.loader.exec_module(_db_mod)

DocsDB = _db_mod.DocsDB


@pytest.fixture
def db(tmp_path):
    """Create a fresh DocsDB for each test."""
    db_path = tmp_path / "test_export_detailed.db"
    db = DocsDB(db_path, embedding_dims=4)
    yield db
    db.close()


def test_export_jsonl_detailed_fields(db):
    """Verifies every field in the exported JSON for library, version, and chunk."""
    lib_id = db.upsert_library(
        name="test_lib",
        docs_url="https://test.com",
        registry="npm",
        description="A test library",
    )
    ver_id = db.upsert_version(lib_id, version="1.0.0", docs_url="https://test.com")
    db.add_chunks(
        ver_id,
        lib_id,
        [
            {
                "content": "chunk 1 content",
                "title": "Title 1",
                "url": "https://test.com/1",
                "heading_path": "H1",
                "chunk_index": 0,
            }
        ],
        embeddings=[[0.1, 0.2, 0.3, 0.4]],
    )

    jsonl = db.export_jsonl()
    lines = [json.loads(line) for line in jsonl.strip().split("\n")]

    # Library verification
    lib = next(item for item in lines if item["_type"] == "library")
    assert lib["id"] == lib_id
    assert lib["name"] == "test_lib"
    assert lib["docs_url"] == "https://test.com"
    assert lib["registry"] == "npm"
    assert lib["description"] == "A test library"
    assert "created_at" in lib
    assert "updated_at" in lib

    # Version verification
    ver = next(item for item in lines if item["_type"] == "version")
    assert ver["id"] == ver_id
    assert ver["library_id"] == lib_id
    assert ver["version"] == "1.0.0"
    assert ver["docs_url"] == "https://test.com"
    assert "indexed_at" in ver
    assert "page_count" in ver
    assert "chunk_count" in ver
    assert "status" in ver

    # Chunk verification
    chunk = next(item for item in lines if item["_type"] == "chunk")
    assert "id" in chunk
    assert chunk["version_id"] == ver_id
    assert chunk["library_id"] == lib_id
    assert chunk["url"] == "https://test.com/1"
    assert chunk["title"] == "Title 1"
    assert chunk["chunk_index"] == 0
    assert chunk["content"] == "chunk 1 content"
    assert chunk["heading_path"] == "H1"
    assert "created_at" in chunk


def test_export_jsonl_sorting(db):
    """Verifies that libraries are sorted by name, versions by library_id, and chunks by library_id and chunk_index."""
    lib_b = db.upsert_library(name="lib_b")
    lib_a = db.upsert_library(name="lib_a")

    ver_b = db.upsert_version(lib_b, version="1.0.0")
    ver_a = db.upsert_version(lib_a, version="1.0.0")

    db.add_chunks(
        ver_b,
        lib_b,
        [
            {"content": "b2", "chunk_index": 1},
            {"content": "b1", "chunk_index": 0},
        ],
    )
    db.add_chunks(
        ver_a,
        lib_a,
        [
            {"content": "a1", "chunk_index": 0},
        ],
    )

    jsonl = db.export_jsonl()
    lines = [json.loads(line) for line in jsonl.strip().split("\n")]

    libs = [item["name"] for item in lines if item["_type"] == "library"]
    assert libs == ["lib_a", "lib_b"]  # sorted by name

    versions = [item["library_id"] for item in lines if item["_type"] == "version"]
    assert versions == sorted([lib_a, lib_b])  # sorted by library_id

    chunks = [item["content"] for item in lines if item["_type"] == "chunk"]
    # chunks for lib_a come first (lib_a < lib_b), then chunks for lib_b sorted by index
    # We need to know which lib_id is smaller
    if lib_a < lib_b:
        assert chunks == ["a1", "b1", "b2"]
    else:
        assert chunks == ["b1", "b2", "a1"]


def test_export_jsonl_with_nulls(db):
    """Verifies that optional fields (docs_url, registry, description) can be null and are exported as such."""
    db.upsert_library(name="null_lib")  # docs_url, registry, description will be None

    jsonl = db.export_jsonl()
    lines = [json.loads(line) for line in jsonl.strip().split("\n")]
    lib = next(item for item in lines if item["_type"] == "library")

    assert lib["docs_url"] is None
    assert lib["registry"] is None
    assert lib["description"] is None


def test_export_jsonl_no_embeddings(db):
    """Explicitly verifies that no embeddings/vectors are included in the JSONL output."""
    lib_id = db.upsert_library(name="vec_lib")
    ver_id = db.upsert_version(lib_id)
    db.add_chunks(
        ver_id,
        lib_id,
        [{"content": "vec content"}],
        embeddings=[[0.1, 0.2, 0.3, 0.4]],
    )

    jsonl = db.export_jsonl()
    lines = [json.loads(line) for line in jsonl.strip().split("\n")]
    chunk = next(item for item in lines if item["_type"] == "chunk")

    assert "content" in chunk
    assert "embedding" not in chunk
    assert "vector" not in chunk
    # And check that the full JSON does not contain the word 'embedding' as a key
    assert '"embedding"' not in jsonl
    assert '"vector"' not in jsonl


def test_export_jsonl_to_file_demo(db, tmp_path):
    """Demonstrates exporting to a file (using the return string) to satisfy the rationale in the issue."""
    db.upsert_library(name="file_lib")

    # User's desired workflow:
    jsonl_data = db.export_jsonl()
    output_file = tmp_path / "export.jsonl"
    output_file.write_text(jsonl_data)

    # Verify it was written correctly
    read_data = output_file.read_text()
    assert read_data == jsonl_data
    assert '"name":"file_lib"' in read_data
