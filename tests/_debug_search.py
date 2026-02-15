"""Debug script to investigate search returning 0 results."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from wet_mcp.config import settings
from wet_mcp.db import DocsDB

docs_db = DocsDB(settings.get_db_path(), embedding_dims=768)

FAIL_IDS = [
    "pytest",
    "celery",
    "sanic",
    "aiohttp",
    "tensorflow",
    "rich",
    "blessed",
    "hypothesis",
    "factory-boy",
    "twisted",
    "marshmallow",
]

for name in FAIL_IDS:
    lib = docs_db.get_library(name)
    if not lib:
        print(f"{name}: NOT FOUND in DB")
        continue

    lid = lib["id"]
    chunks = docs_db._conn.execute(
        "SELECT COUNT(*) as cnt FROM doc_chunks WHERE library_id = ?", (lid,)
    ).fetchone()
    cnt = dict(chunks)["cnt"]

    # Sample content
    sample = docs_db._conn.execute(
        "SELECT SUBSTR(content, 1, 300) as preview FROM doc_chunks WHERE library_id = ? LIMIT 3",
        (lid,),
    ).fetchall()

    # Check FTS5 for ANY content from this library
    fts_test = docs_db._conn.execute(
        """
        SELECT COUNT(*) as cnt
        FROM doc_chunks_fts f
        JOIN doc_chunks c ON f.rowid = c.rowid
        WHERE c.library_id = ?
    """,
        (lid,),
    ).fetchone()
    fts_cnt = dict(fts_test)["cnt"]

    print(f"\n{'='*60}")
    print(f"{name}: chunks={cnt}, fts_match={fts_cnt}")
    print(f"  library_id={lid}")

    for i, s in enumerate(sample):
        preview = dict(s)["preview"]
        print(f"  chunk[{i}]: {repr(preview[:150])}")

    # Try simple FTS search
    try:
        r = docs_db._conn.execute(
            """
            SELECT f.id
            FROM doc_chunks_fts f
            JOIN doc_chunks c ON f.id = c.id
            WHERE doc_chunks_fts MATCH 'test'
            AND c.library_id = ?
            LIMIT 3
        """,
            (lid,),
        ).fetchall()
        print(f"  FTS 'test' + lib filter: {len(r)} results")
    except Exception as e:
        print(f"  FTS error: {e}")

    # Try without library filter
    try:
        r = docs_db._conn.execute(
            """
            SELECT c.library_id, COUNT(*) as cnt
            FROM doc_chunks_fts f
            JOIN doc_chunks c ON f.id = c.id
            WHERE doc_chunks_fts MATCH 'test'
            GROUP BY c.library_id
            ORDER BY cnt DESC
            LIMIT 5
        """
        ).fetchall()
        print("  FTS 'test' top libraries:")
        for row in r:
            d = dict(row)
            lib_row = docs_db._conn.execute(
                "SELECT name FROM libraries WHERE id = ?", (d["library_id"],)
            ).fetchone()
            print(
                f"    {dict(lib_row)['name'] if lib_row else d['library_id']}: {d['cnt']} chunks"
            )
    except Exception as e:
        print(f"  Error: {e}")

docs_db.close()
