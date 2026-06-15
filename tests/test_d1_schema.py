import sqlite3
from pathlib import Path


def test_d1_schema_fts5_content_sync():
    conn = sqlite3.connect(":memory:")
    conn.executescript(Path("migrations/0001_init_wet.sql").read_text(encoding="utf-8"))
    conn.execute(
        "INSERT INTO doc_chunks (id, version_id, library_id, url, title, chunk_index, content, heading_path, created_at)"
        " VALUES (?,?,?,?,?,?,?,?,?)",
        (
            "c1",
            "v1",
            "lib1",
            "https://x",
            "API",
            0,
            "async function definition",
            "API > funcs",
            0.0,
        ),
    )
    row = conn.execute(
        "SELECT bm25(doc_chunks_fts, 0.0, 2.0, 3.0, 2.0) AS s FROM doc_chunks_fts WHERE doc_chunks_fts MATCH ?",
        ('"async"*',),
    ).fetchone()
    assert row is not None  # trigger synced row into FTS5, bm25 weights accepted
    conn.execute("DELETE FROM doc_chunks WHERE id = 'c1'")
    gone = conn.execute(
        "SELECT * FROM doc_chunks_fts WHERE doc_chunks_fts MATCH ?", ('"async"*',)
    ).fetchone()
    assert gone is None  # external-content delete trigger removed it
