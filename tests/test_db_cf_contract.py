"""DocsDBCfBackend must satisfy the whole DocsDB contract, not part of it.

A partial backend does not fail at startup, it fails mid-index: chunks get
written by `add_chunks`, then the next call raises AttributeError inside a
log-only `except Exception`, so the version never reaches status='indexed' and
every subsequent request re-indexes it. `server._missing_docs_db_methods` is the
boot-time gate; this module keeps it satisfied and pins the behaviour of the
methods that gate only proves are *present*.
"""

from pathlib import Path

import pytest
from conftest_cf import FakeD1Http, FakeVectorizeHttp

from wet_mcp.backends.d1 import D1Backend
from wet_mcp.backends.vectorize import VectorizeBackend
from wet_mcp.db_cf import DocsDBCfBackend
from wet_mcp.server import _missing_docs_db_methods

DDL = "\n".join(
    p.read_text(encoding="utf-8") for p in sorted(Path("migrations").glob("*.sql"))
)


def _backend():
    d1 = D1Backend("http://d1.internal", http=FakeD1Http(DDL))
    vec = VectorizeBackend(
        "http://vectorize.internal", idx="wet", http=FakeVectorizeHttp()
    )
    return DocsDBCfBackend(d1, vec, embedding_dims=768)


def _seeded(db):
    lib_id = db.upsert_library("alpha", docs_url="https://a")
    ver_id = db.upsert_version(lib_id, "1.0", docs_url="https://a")
    return lib_id, ver_id


def test_cf_backend_implements_every_docs_db_method():
    """The boot gate in make_docs_db() must find nothing missing."""
    assert _missing_docs_db_methods(_backend()) == []


def test_mark_version_indexed_sets_status_and_counts():
    """The exact call whose absence cost 11 weeks of silent re-indexing."""
    db = _backend()
    _lib_id, ver_id = _seeded(db)
    db.mark_version_indexed(ver_id, 12, 340)
    row = db._d1.fetchone("SELECT * FROM versions WHERE id = ?", [ver_id])
    assert row["status"] == "indexed"
    assert (row["page_count"], row["chunk_count"]) == (12, 340)
    assert row["indexed_at"] > 0


def test_mark_library_indexed_records_time_and_versions():
    db = _backend()
    lib_id, _ver_id = _seeded(db)
    db.mark_library_indexed(lib_id, total_versions=3)
    row = db._d1.fetchone("SELECT * FROM libraries WHERE id = ?", [lib_id])
    assert row["last_indexed_at"] > 0
    assert row["total_versions"] == 3


def test_mark_library_indexed_without_total_leaves_count_alone():
    db = _backend()
    lib_id, _ver_id = _seeded(db)
    db.mark_library_indexed(lib_id, total_versions=5)
    db.mark_library_indexed(lib_id)
    row = db._d1.fetchone("SELECT * FROM libraries WHERE id = ?", [lib_id])
    assert row["total_versions"] == 5


def test_mark_metadata_seeded_is_distinct_from_indexed():
    """A Tier-1 seed must stay distinguishable from a real index."""
    db = _backend()
    lib_id, _ver_id = _seeded(db)
    db.mark_metadata_seeded(lib_id)
    row = db._d1.fetchone("SELECT * FROM libraries WHERE id = ?", [lib_id])
    assert row["metadata_seeded_at"] > 0
    assert row["last_indexed_at"] is None


def test_clear_version_chunks_removes_rows_and_vectors():
    """Chunks and their vectors go together, or search returns ghosts."""
    db = _backend()
    lib_id, ver_id = _seeded(db)
    chunks = [
        {
            "id": f"c{i}",
            "url": "https://a/p",
            "title": "T",
            "chunk_index": i,
            "content": f"content number {i}",
            "heading_path": "T",
        }
        for i in range(3)
    ]
    db.add_chunks(ver_id, lib_id, chunks, embeddings=[[0.1] * 768 for _ in chunks])
    assert len(db._vec._http.vectors) == 3

    removed = db.clear_version_chunks(ver_id)

    assert removed == 3
    assert (
        db._d1.execute("SELECT id FROM doc_chunks WHERE version_id = ?", [ver_id]) == []
    )
    assert db._vec._http.vectors == {}, "vectors outlived their chunks -> ghost hits"


def test_clear_version_chunks_on_empty_version_returns_zero():
    db = _backend()
    _lib_id, ver_id = _seeded(db)
    assert db.clear_version_chunks(ver_id) == 0


def test_project_context_roundtrip():
    db = _backend()
    locked = [{"id": "lib1", "version": "1.0"}]
    db.upsert_project_context("/repo", locked)
    got = db.get_project_context("/repo")
    assert got is not None
    assert got["locked_libraries"] == locked
    assert got["project_path"] == "/repo"


def test_upsert_project_context_updates_without_duplicating():
    db = _backend()
    db.upsert_project_context("/repo", [{"id": "lib1", "version": "1.0"}])
    created = db.get_project_context("/repo")["created_at"]
    db.upsert_project_context("/repo", [{"id": "lib2", "version": "2.0"}])
    got = db.get_project_context("/repo")
    assert got["locked_libraries"] == [{"id": "lib2", "version": "2.0"}]
    assert got["created_at"] == created
    rows = db._d1.execute("SELECT project_path FROM project_context", [])
    assert len(rows) == 1


def test_get_project_context_missing_returns_none():
    assert _backend().get_project_context("/never-locked") is None


def test_touch_project_context_advances_last_used():
    db = _backend()
    db.upsert_project_context("/repo", [])
    db._d1.execute(
        "UPDATE project_context SET last_used_at = ? WHERE project_path = ?",
        [1.0, "/repo"],
    )
    db.touch_project_context("/repo")
    assert db.get_project_context("/repo")["last_used_at"] > 1.0


def test_close_is_safe_and_repeatable():
    """No persistent handle exists to close; it must not pretend otherwise."""
    db = _backend()
    db.close()
    db.close()
    assert db.stats()["libraries"] == 0  # backend still usable


def test_add_chunks_stays_inside_the_d1_parameter_cap():
    """The live 13-column INSERT, measured at the real call site.

    Guards the whole chain, not just D1Backend's arithmetic: if a column is
    ever added to doc_chunks, this fails here rather than as a swallowed
    non-200 that writes nothing.
    """
    import json as _json

    captured = []

    class RecordingHttp:
        def __init__(self, inner):
            self._inner = inner

        def request(self, method, url, data=None, headers=None):
            if url.endswith(("/query", "/batch")):
                captured.append(_json.loads(data.decode()))
            return self._inner.request(method, url, data, headers)

    d1 = D1Backend("http://d1.internal", http=RecordingHttp(FakeD1Http(DDL)))
    vec = VectorizeBackend(
        "http://vectorize.internal", idx="wet", http=FakeVectorizeHttp()
    )
    db = DocsDBCfBackend(d1, vec, embedding_dims=768)
    lib_id = db.upsert_library("alpha", docs_url="https://a")
    ver_id = db.upsert_version(lib_id, "1.0", docs_url="https://a")

    db.add_chunks(
        ver_id,
        lib_id,
        [
            {
                "id": f"c{i}",
                "url": "https://a/p",
                "title": "T",
                "chunk_index": i,
                "content": f"body {i}",
                "heading_path": "T",
            }
            for i in range(30)
        ],
        embeddings=None,
    )

    inserts = [
        s
        for p in captured
        for s in (p if isinstance(p, list) else [p])
        if "INSERT INTO doc_chunks" in s["sql"]
    ]
    assert inserts, "no doc_chunks INSERT was captured"
    widths = [len(s["params"]) for s in inserts]
    assert max(widths) <= 100
    # 13 columns against a 100-parameter cap: 7 rows / 91 params per statement.
    assert widths == [91, 91, 91, 91, 26]
    assert db.stats()["chunks"] == 30


@pytest.mark.parametrize("method", ["export_jsonl", "import_jsonl"])
def test_jsonl_sync_degrades_loudly(method):
    """File-based DB sync is meaningless on CF -- say so, do not return empties.

    Returning "" or {"chunks": 0} would look exactly like a successful sync of
    an empty store, which is the failure mode this whole repair exists to kill.
    """
    db = _backend()
    args = () if method == "export_jsonl" else ("{}",)
    with pytest.raises(NotImplementedError) as exc:
        getattr(db, method)(*args)
    message = str(exc.value)
    assert "cf-d1" in message
    assert "Vectorize" in message  # names why, and what holds the data instead
