"""Schema parity between the local SQLite DocsDB and the D1 migrations.

wrangler owns the D1 schema; `db.py` owns the SQLite one. Anything `DocsDBCfBackend`
reads or writes has to exist in BOTH, and nothing but the sqlite-vec table may be
missing from D1 (D1 cannot load the extension).
"""

import sqlite3
from pathlib import Path

MIGRATIONS = Path("migrations")


def _d1_conn():
    conn = sqlite3.connect(":memory:")
    for path in sorted(MIGRATIONS.glob("*.sql")):
        conn.executescript(path.read_text(encoding="utf-8"))
    return conn


def _cols(conn, table):
    return {r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def test_project_context_table_exists_on_d1():
    """`upsert_project_context` needs this table; 0001 never created it."""
    conn = _d1_conn()
    assert _cols(conn, "project_context") == {
        "project_path",
        "locked_libraries",
        "created_at",
        "last_used_at",
    }


def test_project_context_roundtrips():
    conn = _d1_conn()
    conn.execute(
        "INSERT INTO project_context (project_path, locked_libraries, created_at,"
        " last_used_at) VALUES (?,?,?,?)",
        ("/repo", '[{"id": "lib1", "version": "1.0"}]', 1.0, 1.0),
    )
    row = conn.execute(
        "SELECT locked_libraries FROM project_context WHERE project_path = ?",
        ("/repo",),
    ).fetchone()
    assert row[0] == '[{"id": "lib1", "version": "1.0"}]'


def test_libraries_has_metadata_seeded_at():
    """`mark_metadata_seeded` writes this column; 0001 omitted it.

    Without it a Tier-1 warmup seed is indistinguishable from a real index.
    """
    assert "metadata_seeded_at" in _cols(_d1_conn(), "libraries")


def test_d1_tables_match_local_docsdb():
    """The only table allowed to be D1-absent is the sqlite-vec virtual one."""
    from wet_mcp.db import DocsDB

    local_path = Path("__schema_parity.db")
    try:
        DocsDB(local_path, embedding_dims=0).close()
        local = sqlite3.connect(local_path)
        names = {
            r[0]
            for r in local.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
            if not r[0].startswith("sqlite_")
        }
        local.close()
    finally:
        local_path.unlink(missing_ok=True)

    d1 = _d1_conn()
    d1_names = {
        r[0]
        for r in d1.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        if not r[0].startswith("sqlite_")
    }

    missing = {n for n in names - d1_names if not n.startswith("doc_chunks_vec")}
    assert not missing, f"tables present locally but missing from D1: {sorted(missing)}"
