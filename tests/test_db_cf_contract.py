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
from mcp_core.storage.d1 import D1_MAX_BOUND_PARAMS, D1Backend
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


def test_neighbour_prefetch_stays_inside_the_d1_parameter_cap():
    """The read path's turn at the bug PR #1601 fixed for the write path.

    Reproduces the crash captured from the deployed worker by `wrangler tail`
    on 2026-08-03: `search(action="docs", library="fastapi")` came back as
    "Server disconnected without sending a response" because this prefetch
    batched by ROWS (100) while D1 caps PARAMETERS (100), so a full batch of
    three-column keys sent 300 and D1 answered `D1_ERROR: too many SQL
    variables at offset 376`, killing the container mid-request.

    Asserts the parameter count actually bound per statement, not merely that
    search() returns -- the fake D1 is real sqlite, whose own variable limit is
    far higher, so a row-batched statement passes right through it.
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
    lib_id, ver_id = _seeded(db)
    # 60 distinct urls -> each hit asks for its idx-1 and idx+1 neighbour ->
    # 120 distinct keys, which needs several batches even after the fix.
    db.add_chunks(
        ver_id,
        lib_id,
        [
            {
                "url": f"https://a/p{i}",
                "title": "T",
                "chunk_index": 0,
                "content": f"widget documentation page {i}",
                "heading_path": "T",
            }
            for i in range(60)
        ],
        embeddings=None,
    )

    captured.clear()
    db.search("widget", limit=40)

    prefetch = [
        s
        for p in captured
        for s in (p if isinstance(p, list) else [p])
        if "IN (VALUES" in s["sql"]
    ]
    assert prefetch, "no neighbour-context prefetch was captured"
    widths = [len(s["params"]) for s in prefetch]
    assert max(widths) <= D1_MAX_BOUND_PARAMS, (
        f"prefetch bound {max(widths)} parameters in one statement; D1 caps a "
        f"query at {D1_MAX_BOUND_PARAMS} and drops the container over it"
    )
    assert len(prefetch) > 1, "corpus too small to have exercised batching at all"
    # 3 columns against a 100-parameter cap: 33 keys / 99 params per statement.
    assert widths == [99, 99, 99, 63]
    # Every key still got looked up -- the cap is respected by splitting the
    # work, not by dropping any of it.
    assert sum(widths) == 120 * 3


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


# ---------------------------------------------------------------------------
# Column parity: `libraries`.
#
# The libraries row is not a label, it is control state. `_search_cached_index`
# reads `discovery_version` off it and forces a full re-index whenever the
# stored value trails `sources.docs.DISCOVERY_VERSION`. `db_cf.upsert_library`
# never wrote the column and took the rest of DocsDB's metadata as `**extra`,
# which it dropped -- so a cf-d1 store answered `indexing_in_progress` forever,
# re-indexing on every call, with 50 perfectly good chunks already in D1.
#
# Same failure class as #1618 (chunk id) and #1623 (chunk column fallbacks):
# `_missing_docs_db_methods` only matches method NAMES, so what a method
# actually writes drifts unseen. Compare whole rows, not one column.
# ---------------------------------------------------------------------------

# Every `libraries` column both stores own and either writer can set. `id` /
# `created_at` / `updated_at` are excluded (opaque or wall-clock), as are the
# columns owned by mark_library_indexed / mark_metadata_seeded.
_LIBRARY_PARITY_COLUMNS = (
    "name",
    "docs_url",
    "registry",
    "description",
    "canonical_name",
    "homepage",
    "github_url",
    "package_managers",
    "tier",
    "discovery_version",
)

# Exactly what `sources.docs._index_library` passes in production.
_FULL_LIBRARY_KWARGS = {
    "docs_url": "https://alpha.dev",
    "registry": "pypi",
    "description": "Alpha reads and writes configuration files.",
    "tier": 1,
    "package_managers": ["pip", "uv"],
    "homepage": "https://alpha.dev/home",
    "github_url": "https://github.com/alpha/alpha",
    "canonical_name": "Alpha",
}


def _library_rows(tmp_path, name, calls):
    """Apply the same upsert sequence to both backends; return both rows."""
    local = DocsDB(tmp_path / "docs.db")
    cf = _backend()
    for kwargs in calls:
        local.upsert_library(name, **kwargs)
        cf.upsert_library(name, **kwargs)
    lookup = name.lower().strip()
    return local.get_library(lookup), cf.get_library(lookup)


def _parity(row):
    assert row is not None, "the library row is missing entirely"
    return {c: row.get(c) for c in _LIBRARY_PARITY_COLUMNS}


def test_both_backends_insert_the_same_library_row(tmp_path):
    """A first upsert must land the same metadata in D1 as in SQLite.

    `db_cf.upsert_library` accepted `registry` / `description` / `tier` /
    `package_managers` / `homepage` / `github_url` / `canonical_name` as
    `**extra` and wrote none of them, so the Tier 1 warmup seeded rows on
    cf-d1 that held nothing but a name.
    """
    local_row, cf_row = _library_rows(tmp_path, "alpha", [_FULL_LIBRARY_KWARGS])
    assert _parity(cf_row) == _parity(local_row)


def test_both_backends_stamp_discovery_version_on_insert(tmp_path):
    """The stamp itself, named, because it is what breaks the search path."""
    from wet_mcp.sources.docs import DISCOVERY_VERSION

    local_row, cf_row = _library_rows(
        tmp_path, "alpha", [{"docs_url": "https://alpha.dev"}]
    )
    assert local_row["discovery_version"] == DISCOVERY_VERSION
    assert cf_row["discovery_version"] == DISCOVERY_VERSION


def test_reupsert_restamps_discovery_version_on_an_existing_row(tmp_path):
    """The UPDATE path is the one that heals production.

    Prod D1 already holds rows written at `discovery_version = 0`. Stamping
    only on INSERT would leave every one of them re-indexing forever, because
    the row is never re-inserted -- only ever updated.
    """
    from wet_mcp.sources.docs import DISCOVERY_VERSION

    cf = _backend()
    lib_id = cf.upsert_library("alpha", docs_url="https://alpha.dev")
    cf._d1.execute("UPDATE libraries SET discovery_version = 0 WHERE id = ?", [lib_id])
    assert cf.get_library("alpha")["discovery_version"] == 0

    cf.upsert_library("alpha", docs_url="https://alpha.dev")
    assert cf.get_library("alpha")["discovery_version"] == DISCOVERY_VERSION


def test_both_backends_update_the_same_library_columns(tmp_path):
    """A second upsert must write the same columns -- and blank the same none.

    DocsDB's UPDATE skips every field the caller left as None; the CF UPDATE
    assigned `docs_url` unconditionally, so a metadata-only re-upsert erased
    the stored docs URL of an already-indexed library.
    """
    local_row, cf_row = _library_rows(
        tmp_path,
        "alpha",
        [
            _FULL_LIBRARY_KWARGS,
            {"registry": "npm", "description": "Alpha, restated."},
        ],
    )
    assert _parity(cf_row) == _parity(local_row)


def test_both_backends_normalise_the_library_name(tmp_path):
    """`get_library` must find what `upsert_library` just wrote, in any casing.

    DocsDB lowercases and strips on both read and write. db_cf did neither, so
    a search for "FastAPI" followed by one for "fastapi" minted two library
    rows and indexed the same docs twice -- the same unbounded re-index this
    module exists to prevent.
    """
    local_row, cf_row = _library_rows(
        tmp_path, "  FastAPI  ", [{"docs_url": "https://f.dev"}]
    )
    assert _parity(cf_row) == _parity(local_row)

    cf = _backend()
    first = cf.upsert_library("FastAPI", docs_url="https://f.dev")
    again = cf.upsert_library("fastapi", docs_url="https://f.dev")
    assert again == first
    assert cf.stats()["libraries"] == 1


def test_a_legacy_unnormalised_row_is_healed_not_orphaned():
    """Normalising the lookup must not strand rows written before the change.

    `libraries` is already populated in production. If the normalised lookup
    simply missed a row stored as "FastAPI", the next upsert would mint a
    second row and the first one's chunks would become unreachable -- a fix
    that loses indexed data is worse than the bug. So the read falls back to
    the raw name and the UPDATE rewrites it in place, keeping the id.

    Measured on prod `wet-docs` before shipping: 0 of 10 library rows had a
    name differing from `lower(trim(name))`, so this covers the mixed-version
    rollout window rather than a known-bad row.
    """
    from wet_mcp.sources.docs import DISCOVERY_VERSION

    cf = _backend()
    # A row exactly as an older container would have written it.
    legacy_id = "legacy-row"
    now = 1.0
    cf._d1.execute(
        "INSERT INTO libraries (id, name, docs_url, created_at, updated_at)"
        " VALUES (?,?,?,?,?)",
        [legacy_id, "  FastAPI  ", "https://f.dev", now, now],
    )
    ver_id = cf.upsert_version(legacy_id, "latest", docs_url="https://f.dev")
    cf.add_chunks(ver_id, legacy_id, [{"content": "fastapi dependency injection"}])
    cf.mark_version_indexed(ver_id, 1, 1)

    # The normalised lookup still reaches it...
    assert cf.get_library("fastapi")["id"] == legacy_id

    # ...and touching it repairs the row rather than replacing it.
    assert cf.upsert_library("FastAPI", docs_url="https://f.dev") == legacy_id
    assert cf.stats()["libraries"] == 1, "a second row was minted; chunks orphaned"

    healed = cf.get_library("fastapi")
    assert healed["id"] == legacy_id
    assert healed["name"] == "fastapi"
    assert healed["discovery_version"] == DISCOVERY_VERSION
    assert cf.get_best_version(legacy_id, "latest")["chunk_count"] == 1


def test_upsert_library_rejects_an_unknown_field(tmp_path):
    """Silently swallowing kwargs is how this bug survived three releases.

    `**extra` made every future column addition a no-op on cf-d1 that nothing
    would report. An unknown field must fail the same way DocsDB fails it.

    Dispatched by name because a literal keyword is a static type error on the
    SQLite side -- which is exactly the report the CF side owed us and did not
    give. Here we want the runtime error, so the call has to get past `ty`.
    """
    method = "upsert_library"
    for db in (_backend(), DocsDB(tmp_path / "docs.db")):
        with pytest.raises(TypeError):
            getattr(db, method)("alpha", not_a_column="x")


def test_both_backends_insert_the_same_version_row(tmp_path):
    """`versions` INSERT parity: a fresh version is 'pending' with zero counts."""
    cols = ("version", "docs_url", "status", "page_count", "chunk_count")

    local = DocsDB(tmp_path / "docs.db")
    local_lib = local.upsert_library("alpha", docs_url="https://alpha.dev")
    local_ver = local.upsert_version(local_lib, "1.0", docs_url="https://alpha.dev")
    local_row = dict(
        local._conn.execute(
            "SELECT * FROM versions WHERE id = ?", (local_ver,)
        ).fetchone()
    )

    cf = _backend()
    cf_lib = cf.upsert_library("alpha", docs_url="https://alpha.dev")
    cf_ver = cf.upsert_version(cf_lib, "1.0", docs_url="https://alpha.dev")
    cf_row = cf._d1.fetchone("SELECT * FROM versions WHERE id = ?", [cf_ver])

    assert {c: cf_row[c] for c in cols} == {c: local_row[c] for c in cols}


async def test_search_cached_index_serves_a_library_indexed_on_cf(monkeypatch):
    """The whole point: an indexed cf-d1 library must be answered, not re-indexed.

    Verified live on prod D1 2026-08-03 -- library `fastapi` held 50
    doc_chunks, `versions.index_state='done'`, `chunk_count=50`, FTS synced
    50/50, and `search(action="docs")` still replied `indexing_in_progress`
    on every call because `discovery_version` read back 0 against a code
    constant of 27.
    """
    from wet_mcp import server

    cf = _backend()
    lib_id = cf.upsert_library(
        "alpha",
        docs_url="https://alpha.dev",
        registry="pypi",
        description="Alpha reads config files.",
    )
    ver_id = cf.upsert_version(lib_id, "latest", docs_url="https://alpha.dev")
    cf.add_chunks(
        ver_id,
        lib_id,
        [
            {
                "url": "https://alpha.dev/retry",
                "title": "Retry",
                "content": "alpha retries a failed request with exponential backoff",
                "heading_path": "Usage > Retry",
            }
        ],
    )
    cf.mark_version_indexed(ver_id, 1, 1)

    async def _no_embedding(*_a, **_k):
        return None

    async def _no_hyde(*_a, **_k):
        return None

    async def _passthrough_rerank(_query, results, limit):
        return results[:limit]

    monkeypatch.setattr(server, "_docs_db", cf)
    monkeypatch.setattr(server, "_embed", _no_embedding)
    monkeypatch.setattr(server, "_rerank_results", _passthrough_rerank)
    monkeypatch.setattr(
        "wet_mcp.sources.search_strategies.generate_hyde_query", _no_hyde
    )

    payload = await server._search_cached_index("alpha", "retry backoff", None, 5)

    assert payload is not None, (
        "an indexed cf-d1 library was reported as needing indexing again"
    )
    assert payload["source"] == "cached_index"
    assert payload["results"], "served an empty result set for an indexed library"


# ---------------------------------------------------------------------------
# `get_best_version` parity (#1626).
#
# "Best" means best SERVABLE, i.e. indexed. `_search_cached_index` reads
# `chunk_count` off whatever this returns and re-indexes when it is 0, so a
# backend that hands back a half-finished version reports a library as
# unservable while another version could have answered.
#
# cf-d1 filtered no status on either branch and never fell back, so the two
# backends disagreed about which version a library can serve. Same class as
# #1618 / #1623 / #1624: the shape gate matches method names, not answers.
# ---------------------------------------------------------------------------


def _version_case(db, lib_name, rows):
    """Build one library with `rows` = [(version, indexed?)]; return its id."""
    lib_id = db.upsert_library(lib_name, docs_url="https://alpha.dev")
    for version, indexed in rows:
        ver_id = db.upsert_version(lib_id, version, docs_url="https://alpha.dev")
        if indexed:
            db.add_chunks(ver_id, lib_id, [{"content": f"body of {version}"}])
            db.mark_version_indexed(ver_id, 1, 1)
    return lib_id


def _best(db, lib_id, target):
    row = db.get_best_version(lib_id, target)
    return None if row is None else (row["version"], row["status"])


@pytest.mark.parametrize(
    ("rows", "target", "expected"),
    [
        # The exact target is indexed -- serve exactly it.
        ([("1.0", True)], "1.0", ("1.0", "indexed")),
        # The exact target exists but never finished indexing, while another
        # version did. Returning the pending row reports "needs indexing" for a
        # library that can be served right now; DocsDB falls back instead.
        ([("1.0", True), ("2.0", False)], "2.0", ("1.0", "indexed")),
        # Nothing is indexed -- both backends must say so rather than hand back
        # a row with no chunks behind it.
        ([("1.0", False)], "1.0", None),
        # No target: newest indexed version, never a pending one.
        ([("1.0", True), ("2.0", False)], None, ("1.0", "indexed")),
    ],
    ids=["target-indexed", "target-pending-other-indexed", "none-indexed", "no-target"],
)
def test_both_backends_pick_the_same_best_version(tmp_path, rows, target, expected):
    local = DocsDB(tmp_path / "docs.db")
    local_lib = _version_case(local, "alpha", rows)

    cf = _backend()
    cf_lib = _version_case(cf, "alpha", rows)

    assert _best(local, local_lib, target) == expected, "SQLite is the reference here"
    assert _best(cf, cf_lib, target) == expected


def test_upsert_version_still_finds_a_pending_row(tmp_path):
    """`upsert_version` must not be filtered by "best" -- it would duplicate.

    Its existence check is a direct unfiltered lookup on both backends. Routing
    it through `get_best_version` once the status filter exists would miss a
    `pending` row and INSERT a second one against
    `UNIQUE(library_id, version)`, which is why the decoupling lands with the
    filter rather than after it.
    """
    for db in (_backend(), DocsDB(tmp_path / "docs.db")):
        lib_id = db.upsert_library("alpha", docs_url="https://alpha.dev")
        first = db.upsert_version(lib_id, "1.0", docs_url="https://alpha.dev")

        # The row is 'pending', so it is invisible to get_best_version...
        assert db.get_best_version(lib_id, "1.0") is None
        # ...and must still be reused rather than duplicated.
        assert db.upsert_version(lib_id, "1.0", docs_url="https://alpha.dev") == first


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
