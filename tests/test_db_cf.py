from pathlib import Path

from conftest_cf import FakeD1Http, FakeVectorizeHttp

from wet_mcp.backends.d1 import D1Backend
from wet_mcp.backends.vectorize import VectorizeBackend
from wet_mcp.db_cf import DocsDBCfBackend

DDL = Path("migrations/0001_init_wet.sql").read_text(encoding="utf-8")


def _backend(ready_after=0):
    d1 = D1Backend("http://d1.internal", http=FakeD1Http(DDL))
    vec = VectorizeBackend(
        "http://vectorize.internal", idx="wet", http=FakeVectorizeHttp(ready_after)
    )
    return DocsDBCfBackend(d1, vec, embedding_dims=768)


def test_add_chunks_then_fts_search():
    db = _backend()
    db.upsert_library("alpha", docs_url="https://a")
    lib = db.get_library("alpha")
    db.upsert_version(lib["id"], "1.0")
    ver = db.get_best_version(lib["id"], "1.0")
    db.add_chunks(
        ver["id"],
        lib["id"],
        [
            {
                "id": "c1",
                "url": "https://a/p1",
                "title": "API",
                "chunk_index": 0,
                "content": "async function handler with error handling",
                "heading_path": "API",
            },
        ],
        embeddings=None,
    )
    results = db.search("function", limit=5)
    assert results and results[0]["content"].startswith("async function")
    assert results[0]["url"] == "https://a/p1"


def test_stats_reports_counts():
    # config(action="status") calls _docs_db.stats(); the CF backend must expose it
    # (regression: wet CF config(status) crashed with "'DocsDBCfBackend' object has no
    # attribute 'stats'", 2026-06-17).
    db = _backend()
    assert db.stats() == {"libraries": 0, "chunks": 0, "vec_enabled": True}
    db.upsert_library("alpha", docs_url="https://a")
    lib = db.get_library("alpha")
    db.upsert_version(lib["id"], "1.0")
    ver = db.get_best_version(lib["id"], "1.0")
    db.add_chunks(
        ver["id"],
        lib["id"],
        [
            {
                "id": "c1",
                "url": "https://a/p1",
                "title": "API",
                "chunk_index": 0,
                "content": "hello world",
                "heading_path": "API",
            },
        ],
        embeddings=None,
    )
    s = db.stats()
    assert s["libraries"] == 1
    assert s["chunks"] == 1
    assert s["vec_enabled"] is True


def test_hybrid_search_applies_rrf_and_url_diversity():
    db = _backend()
    db.upsert_library("alpha", docs_url="https://a")
    lib = db.get_library("alpha")
    db.upsert_version(lib["id"], "1.0")
    ver = db.get_best_version(lib["id"], "1.0")
    chunks = [
        {
            "id": f"c{i}",
            "url": "https://a/same",
            "title": "T",
            "chunk_index": i,
            "content": f"vector search cosine similarity chunk {i}",
            "heading_path": "H",
        }
        for i in range(5)
    ]
    embeddings = [[1.0, 0.0, 0.0] + [0.0] * 765 for _ in chunks]
    db.add_chunks(ver["id"], lib["id"], chunks, embeddings=embeddings)
    results = db.search(
        "vector search", limit=10, query_embedding=[1.0, 0.0, 0.0] + [0.0] * 765
    )
    # URL diversity caps same-url chunks at 2 (db.py max_per_url = 2)
    same_url = [r for r in results if r["url"] == "https://a/same"]
    assert len(same_url) <= 2


QUERIES = [
    "async function",
    "install the package",
    "error handling",
    "rate limit",
    "vector search",
]


def test_cf_search_matches_sqlite_golden(cf_corpus, cf_golden_topk):
    db = _backend()
    for d in cf_corpus:
        db.upsert_library(d["library"], docs_url=d["url"])
        lib = db.get_library(d["library"])
        db.upsert_version(lib["id"], d["version"])
        ver = db.get_best_version(lib["id"], d["version"])
        db.add_chunks(ver["id"], lib["id"], [d], embeddings=None)  # FTS-only parity
    for q in QUERIES:
        cf_top = [r["content"][:40] for r in db.search(q, limit=10)]
        golden = cf_golden_topk[q]
        overlap = len(set(cf_top[:3]) & set(golden[:3]))
        assert overlap >= 2, (
            f"top-3 rank parity failed for {q!r}: {cf_top[:3]} vs {golden[:3]}"
        )


def test_search_fetches_adjacent_context():
    db = _backend()
    db.upsert_library("alpha", docs_url="https://a")
    lib = db.get_library("alpha")
    db.upsert_version(lib["id"], "1.0")
    ver = db.get_best_version(lib["id"], "1.0")
    chunks = []
    for p in range(3):
        for i in range(3):
            chunks.append(
                {
                    "id": f"c_{p}_{i}",
                    "url": f"https://a/p{p}",
                    "title": f"Page {p}",
                    "chunk_index": i,
                    "content": f"page {p} chunk {i}",
                    "heading_path": "API",
                }
            )
    db.add_chunks(ver["id"], lib["id"], chunks, embeddings=None)

    # Search for "chunk 1", should return "page 0 chunk 1", "page 1 chunk 1", "page 2 chunk 1"
    # They should all have context_before (chunk 0) and context_after (chunk 2)
    results = db.search("chunk 1", limit=10)

    found_pages = set()
    for r in results:
        for p in range(3):
            if r["content"] == f"page {p} chunk 1":
                assert r["context_before"] == f"page {p} chunk 0"
                assert r["context_after"] == f"page {p} chunk 2"
                found_pages.add(p)

    assert found_pages == {0, 1, 2}
