"""DocsDBCfBackend must satisfy the whole DocsDB contract, not part of it.

A partial backend does not fail at startup, it fails mid-index: chunks get
written by `add_chunks`, then the next call raises AttributeError inside a
log-only `except Exception`, so the version never reaches status='indexed' and
every subsequent request re-indexes it. `server._missing_docs_db_methods` is the
boot-time gate; this module keeps it satisfied and pins the behaviour of the
methods that gate only proves are *present*.
"""

import copy
import re
from pathlib import Path

import pytest
from conftest_cf import FakeD1Http, FakeVectorizeHttp
from mcp_core.storage.d1 import D1Backend
from mcp_core.storage.vectorize import VectorizeBackend

from wet_mcp.db import DocsDB
from wet_mcp.db_cf import DocsDBCfBackend
from wet_mcp.server import _missing_docs_db_methods
from wet_mcp.sources.docs import chunk_markdown

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


def test_index_state_roundtrips_through_d1():
    """The whole point of the record: it is readable from outside the container.

    A background indexer inside the Cloudflare container logs to a stderr
    nothing collects, so D1 is the only surface where its outcome can be seen.
    """
    db = _backend()
    _lib_id, ver_id = _seeded(db)

    db.set_index_state(ver_id, "running")
    assert db.get_index_state(ver_id)["state"] == "running"

    db.set_index_state(ver_id, "failed", "Could not extract content from https://a")

    state = db.get_index_state(ver_id)
    assert state["state"] == "failed"
    assert state["error"] == "Could not extract content from https://a"
    assert state["updated_at"] > 0
    assert state["version"] == "1.0"


def test_index_state_is_absent_until_something_attempts_an_index():
    """Never-attempted must not read as an outcome."""
    db = _backend()
    _lib_id, ver_id = _seeded(db)
    assert db.get_index_state(ver_id) is None
    assert db.get_index_state("no-such-version") is None


def test_failed_state_does_not_disturb_the_counts():
    """Recording a failure must not zero the chunks the version still serves."""
    db = _backend()
    _lib_id, ver_id = _seeded(db)
    db.mark_version_indexed(ver_id, 12, 340)

    db.set_index_state(ver_id, "failed", "docs host returned 503")

    row = db._d1.fetchone("SELECT * FROM versions WHERE id = ?", [ver_id])
    assert (row["page_count"], row["chunk_count"]) == (12, 340)
    assert row["status"] == "indexed", "a failed retry must not unpublish good data"


def test_index_status_summarizes_what_config_status_reports():
    """config(action='status') reads this to say why chunks is zero."""
    db = _backend()
    lib_id, ver_id = _seeded(db)
    other_ver = db.upsert_version(lib_id, "2.0", docs_url="https://a")
    db.set_index_state(ver_id, "failed", "Could not extract content")
    db.set_index_state(other_ver, "running")

    status = db.index_status()

    assert status["counts"] == {"failed": 1, "running": 1}
    recent = {r["version"]: r for r in status["recent"]}
    assert recent["1.0"]["error"] == "Could not extract content"
    assert recent["1.0"]["library"] == "alpha"
    assert recent["2.0"]["state"] == "running"


def test_index_state_writes_use_a_fixed_parameter_count():
    """Never scale a D1 statement by row count -- that is what PR #1601 fixed."""
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
    for i in range(20):
        db.set_index_state(
            db.upsert_version(lib_id, f"{i}.0", docs_url="https://a"), "running"
        )

    updates = [
        s
        for p in captured
        for s in (p if isinstance(p, list) else [p])
        if "UPDATE versions SET index_state" in s["sql"]
    ]
    assert len(updates) == 20
    assert {len(s["params"]) for s in updates} == {4}


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


# ---------------------------------------------------------------------------
# Shape parity: both backends must accept the *same* chunker output.
#
# `_missing_docs_db_methods` proves the two classes expose the same method
# NAMES. It cannot prove they accept the same INPUTS, and they did not: the CF
# row builder read `c["id"]`, a key `chunk_markdown` has never emitted, so
# `server._background_index_and_search` -- which passes the chunker's list
# straight through -- raised KeyError on every cf-d1 index.
# ---------------------------------------------------------------------------

CHUNKER_INPUT = """# Alpha

Alpha is a small library for reading and writing configuration files.
It ships a single entry point and keeps its dependency list empty.

## Installation

Install the package from PyPI with your package manager of choice.
The wheel is pure Python and needs no compiler on any supported platform.

```bash
pip install alpha
```

## Usage

Load a document, mutate it in place, then write it back to disk.
Every value keeps the type it had in the source file, so round-tripping
a document never rewrites unrelated keys.

```python
import alpha

doc = alpha.load("config.toml")
doc["timeout"] = 30
alpha.dump(doc, "config.toml")
```

### Error handling

A malformed document raises `alpha.ParseError` with the byte offset of the
first token that could not be read, which is enough to point an editor at
the offending line without re-parsing the file.
"""


def _chunker_output() -> list[dict]:
    """Real `chunk_markdown` output -- not a hand-written stand-in.

    A hand-written fixture is what let this bug through: every existing CF
    test spells `"id"` into its chunks, so none of them exercised the shape
    production actually produces.
    """
    chunks = chunk_markdown(CHUNKER_INPUT, url="https://alpha.dev/guide")
    assert len(chunks) > 1, "fixture must exercise the real chunker"
    assert all("id" not in c for c in chunks), (
        "the chunker mints no ids -- if that changes, identity ownership moved "
        "and both backends need revisiting"
    )
    return chunks


def test_both_backends_accept_raw_chunker_output(tmp_path):
    """The exact call `server._background_index_and_search` makes, on both."""
    chunks = _chunker_output()

    local = DocsDB(tmp_path / "docs.db")
    local_lib = local.upsert_library("alpha", docs_url="https://alpha.dev")
    local_ver = local.upsert_version(local_lib, "1.0", docs_url="https://alpha.dev")
    assert local.add_chunks(local_ver, local_lib, copy.deepcopy(chunks)) == len(chunks)

    cf = _backend()
    cf_lib, cf_ver = _seeded(cf)
    cf.add_chunks(cf_ver, cf_lib, copy.deepcopy(chunks))
    assert cf.stats()["chunks"] == len(chunks)


def test_cf_generated_chunk_ids_match_the_sqlite_scheme(tmp_path):
    """Identity is owned by the backend, and both mint it the same way.

    Asserted against ids the SQLite backend actually produced rather than a
    copied literal, so a change to `db._prepare_chunk_rows` fails here instead
    of leaving the two stores quietly disagreeing on id shape.
    """
    chunks = _chunker_output()

    local = DocsDB(tmp_path / "docs.db")
    local_lib = local.upsert_library("alpha", docs_url="https://alpha.dev")
    local_ver = local.upsert_version(local_lib, "1.0", docs_url="https://alpha.dev")
    local.add_chunks(local_ver, local_lib, copy.deepcopy(chunks))
    local_ids = [r[0] for r in local._conn.execute("SELECT id FROM doc_chunks")]

    cf = _backend()
    cf_lib, cf_ver = _seeded(cf)
    cf.add_chunks(cf_ver, cf_lib, copy.deepcopy(chunks))
    cf_ids = [r["id"] for r in cf._d1.execute("SELECT id FROM doc_chunks", [])]

    assert len(cf_ids) == len(local_ids) == len(chunks)
    assert len(set(cf_ids)) == len(cf_ids), "a duplicate id overwrites a chunk"
    assert {len(i) for i in cf_ids} == {len(i) for i in local_ids}
    assert all(re.fullmatch(r"[0-9a-f]+", i) for i in cf_ids)


def test_cf_vector_ids_match_the_chunk_rows_they_belong_to():
    """One id per chunk, shared by its D1 row and its vector.

    The row and the vector are built in two separate comprehensions; minting
    an id independently in each would store vectors that no chunk row claims,
    which `clear_version_chunks` then cannot delete and `search` returns as
    hits with no content behind them.
    """
    chunks = _chunker_output()
    cf = _backend()
    cf_lib, cf_ver = _seeded(cf)

    cf.add_chunks(cf_ver, cf_lib, chunks, embeddings=[[0.1] * 768 for _ in chunks])

    row_ids = {
        r["id"]
        for r in cf._d1.execute(
            "SELECT id FROM doc_chunks WHERE version_id = ?", [cf_ver]
        )
    }
    assert row_ids == set(cf._vec._http.vectors)


def _local_store(tmp_path):
    db = DocsDB(tmp_path / "docs.db")
    lib_id = db.upsert_library("alpha", docs_url="https://alpha.dev")
    ver_id = db.upsert_version(lib_id, "1.0", docs_url="https://alpha.dev")
    return db, lib_id, ver_id


def test_both_backends_default_chunk_index_to_its_place_in_the_batch(tmp_path):
    """An absent `chunk_index` must resolve identically, not to 0 on one side.

    `DocsDB._prepare_chunk_rows` falls back to the chunk's position in the
    batch; the CF backend fell back to a constant 0. Nothing raises either
    way, so a cf-d1 store would simply hold a batch flattened onto index 0
    while SQLite held 0..n-1 -- and `_build_results_cf` prefetches a hit's
    neighbours by (url, version_id, chunk_index +/- 1), so `context_before` /
    `context_after` would silently never resolve on CF alone.

    Latent today: chunk_markdown / chunk_llms_txt always emit the key. It is
    reachable the moment a caller does what `DocsDB` documents as legal --
    `test_db.py::test_add_chunks_minimal_fields` passes content and nothing
    else.
    """
    chunks = _chunker_output()
    for c in chunks:
        del c["chunk_index"]

    local, local_lib, local_ver = _local_store(tmp_path)
    local.add_chunks(local_ver, local_lib, copy.deepcopy(chunks))
    local_idx = [
        r[0]
        for r in local._conn.execute(
            "SELECT chunk_index FROM doc_chunks ORDER BY rowid"
        )
    ]

    cf = _backend()
    cf_lib, cf_ver = _seeded(cf)
    cf.add_chunks(cf_ver, cf_lib, copy.deepcopy(chunks))
    cf_idx = [
        r["chunk_index"]
        for r in cf._d1.execute(
            "SELECT chunk_index FROM doc_chunks WHERE version_id = ? ORDER BY rowid",
            [cf_ver],
        )
    ]

    assert local_idx == list(range(len(chunks))), "SQLite is the reference here"
    assert cf_idx == local_idx


def test_both_backends_store_a_content_only_chunk_identically(tmp_path):
    """Every fallback in the CF row builder, checked against SQLite at once.

    `chunk_index` was not the only default that had drifted: url / title /
    heading_path fell back to NULL on CF and to '' on SQLite. Comparing the
    whole row rather than one column keeps the next added column from
    diverging unnoticed -- the shape gate `_missing_docs_db_methods` only
    matches method names.
    """
    cols = (
        "url",
        "title",
        "chunk_index",
        "content",
        "heading_path",
        "section",
        "topic",
        "content_hash",
        "token_count",
    )
    chunks = [{"content": f"paragraph number {i}"} for i in range(3)]

    local, local_lib, local_ver = _local_store(tmp_path)
    local.add_chunks(local_ver, local_lib, copy.deepcopy(chunks))
    local_rows = [
        tuple(r)
        for r in local._conn.execute(
            f"SELECT {', '.join(cols)} FROM doc_chunks ORDER BY rowid"
        )
    ]

    cf = _backend()
    cf_lib, cf_ver = _seeded(cf)
    cf.add_chunks(cf_ver, cf_lib, copy.deepcopy(chunks))
    cf_rows = [
        tuple(r[c] for c in cols)
        for r in cf._d1.execute(
            f"SELECT {', '.join(cols)} FROM doc_chunks"
            " WHERE version_id = ? ORDER BY rowid",
            [cf_ver],
        )
    ]

    assert cf_rows == local_rows


def test_cf_vector_metadata_repeats_the_chunk_index_of_its_own_row():
    """Vector metadata and D1 row are built apart; they must still agree.

    `search()` filters and orders on the metadata copy, so a metadata
    chunk_index that does not match the row it points at reorders results
    against content that never moved.
    """
    chunks = _chunker_output()
    for c in chunks:
        del c["chunk_index"]

    cf = _backend()
    cf_lib, cf_ver = _seeded(cf)
    cf.add_chunks(cf_ver, cf_lib, chunks, embeddings=[[0.1] * 768 for _ in chunks])

    by_id = {
        r["id"]: r["chunk_index"]
        for r in cf._d1.execute(
            "SELECT id, chunk_index FROM doc_chunks WHERE version_id = ?", [cf_ver]
        )
    }
    assert by_id, "nothing was written"
    for cid, (_values, meta) in cf._vec._http.vectors.items():
        assert meta["chunk_index"] == by_id[cid]


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
