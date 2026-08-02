"""Cloudflare docs DB: relational + FTS5 on D1, vectors on Vectorize.

Public interface mirrors wet_mcp.db.DocsDB (upsert_library / upsert_version /
get_library / get_best_version / add_chunks / search) so server.py is polymorphic.
The ranking pipeline (tiered FTS5, bm25 weights 0/2/3/2, RRF k=60, quality boost,
URL diversity 2/url, adjacent prefetch) is REUSED from db.py, not reimplemented.
"""

from __future__ import annotations

import json
import time
import uuid

from loguru import logger

from wet_mcp.backends.d1 import D1Backend
from wet_mcp.backends.vectorize import VectorizeBackend

# Reuse the exact ranking helpers from the SQLite implementation.
from wet_mcp.db import _build_fts_queries, _chunk_quality_score


class DocsDBCfBackend:
    def __init__(
        self, d1: D1Backend, vectorize: VectorizeBackend, embedding_dims: int = 768
    ) -> None:
        self._d1 = d1
        self._vec = vectorize
        self._embedding_dims = embedding_dims

    def stats(self) -> dict:
        """Return database statistics. Mirrors wet_mcp.db.DocsDB.stats over D1 so
        config(action="status") is polymorphic across the SQLite and CF backends."""
        lib_row = self._d1.fetchone("SELECT COUNT(*) AS n FROM libraries", [])
        chunk_row = self._d1.fetchone("SELECT COUNT(*) AS n FROM doc_chunks", [])
        return {
            "libraries": (lib_row or {}).get("n", 0),
            "chunks": (chunk_row or {}).get("n", 0),
            "vec_enabled": self._vec is not None,
        }

    # --- relational CRUD (parameterized D1) ---

    def upsert_library(self, name: str, docs_url: str | None = None, **extra) -> str:
        existing = self.get_library(name)
        now = time.time()
        if existing:
            self._d1.execute(
                "UPDATE libraries SET docs_url = ?, updated_at = ? WHERE id = ?",
                [docs_url, now, existing["id"]],
            )
            return existing["id"]
        lib_id = str(uuid.uuid4())
        self._d1.execute(
            "INSERT INTO libraries (id, name, docs_url, created_at, updated_at)"
            " VALUES (?,?,?,?,?)",
            [lib_id, name, docs_url, now, now],
        )
        return lib_id

    def get_library(self, name: str) -> dict | None:
        return self._d1.fetchone("SELECT * FROM libraries WHERE name = ?", [name])

    def upsert_version(
        self,
        library_id: str,
        version: str = "latest",
        docs_url: str | None = None,
    ) -> str:
        """Create or get version. Returns version ID.

        Signature and docs_url handling mirror wet_mcp.db.DocsDB.upsert_version:
        both production index call sites pass ``docs_url=``, and an existing row
        gets the new ``docs_url`` written back onto it (a missing one leaves the
        stored value alone).
        """
        existing = self.get_best_version(library_id, version)
        if existing:
            ver_id = existing["id"]
            if docs_url:
                self._d1.execute(
                    "UPDATE versions SET docs_url = ? WHERE id = ?",
                    [docs_url, ver_id],
                )
            return ver_id
        ver_id = str(uuid.uuid4())
        self._d1.execute(
            "INSERT INTO versions (id, library_id, version, docs_url) VALUES (?,?,?,?)",
            [ver_id, library_id, version, docs_url],
        )
        return ver_id

    def get_best_version(
        self, library_id: str, target: str | None = None
    ) -> dict | None:
        if target:
            return self._d1.fetchone(
                "SELECT * FROM versions WHERE library_id = ? AND version = ?",
                [library_id, target],
            )
        return self._d1.fetchone(
            "SELECT * FROM versions WHERE library_id = ? ORDER BY indexed_at DESC LIMIT 1",
            [library_id],
        )

    def add_chunks(
        self,
        version_id: str,
        library_id: str,
        chunks: list[dict],
        embeddings: list[list[float]] | None = None,
    ) -> None:
        now = time.time()
        rows = [
            [
                c["id"],
                version_id,
                library_id,
                c.get("url"),
                c.get("title"),
                c.get("chunk_index", 0),
                c["content"],
                c.get("heading_path"),
                c.get("section"),
                c.get("topic"),
                c.get("content_hash"),
                c.get("token_count"),
                now,
            ]
            for c in chunks
        ]
        # section/topic/content_hash/token_count exist in migrations/0001_init_wet.sql
        # and search() reads them back, so persist them like DocsDB.add_chunks does.
        self._d1.executemany(
            "INSERT INTO doc_chunks (id, version_id, library_id, url, title, chunk_index,"
            " content, heading_path, section, topic, content_hash, token_count,"
            " created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            rows,
        )
        if embeddings:
            vectors = [
                {
                    "id": c["id"],
                    "values": emb,
                    "metadata": {
                        "library_id": library_id,
                        "version_id": version_id,
                        "url": c.get("url", ""),
                        "chunk_index": c.get("chunk_index", 0),
                    },
                }
                for c, emb in zip(chunks, embeddings, strict=False)
            ]
            self._vec.upsert(vectors)
            # Upsert is eventual; block until index is ready so an immediate
            # search() doesn't return empty (mirrors spec risk mitigation).
            self._vec.wait_until_indexed()

    def clear_version_chunks(self, version_id: str) -> int:
        """Drop a version's chunks from D1 and their vectors from Vectorize.

        Vectors go FIRST, and the delete is not error-suppressed. If Vectorize
        refuses, the D1 rows stay as well, leaving the store merely stale --
        the alternative ordering leaves vectors whose chunk row is gone, and
        those come back from search() as hits with no content behind them.

        Returns the number of chunks removed, counted from the ids actually
        read (the D1 HTTP contract returns rows, not a rowcount).
        """
        rows = self._d1.execute(
            "SELECT id FROM doc_chunks WHERE version_id = ?", [version_id]
        )
        ids = [r["id"] for r in rows]
        if not ids:
            return 0
        self._vec.delete_by_ids(ids)
        self._d1.execute("DELETE FROM doc_chunks WHERE version_id = ?", [version_id])
        return len(ids)

    # --- index bookkeeping ---

    def mark_version_indexed(
        self, version_id: str, page_count: int, chunk_count: int
    ) -> None:
        """Mark a version indexed with its counts.

        The absence of exactly this method is what made cf-d1 lose data: the
        indexer wrote chunks, raised AttributeError here inside a log-only
        `except Exception`, and left the version at status='pending' so the
        next request indexed it all over again.
        """
        self._d1.execute(
            "UPDATE versions SET status = 'indexed', indexed_at = ?,"
            " page_count = ?, chunk_count = ? WHERE id = ?",
            [time.time(), page_count, chunk_count, version_id],
        )

    def set_index_state(
        self, version_id: str, state: str, error: str | None = None
    ) -> None:
        """Record an indexing attempt's outcome on D1.

        This is the CF half of the durability fix: a background indexer
        running inside the Cloudflare container writes its logs to a stderr
        nothing collects, so D1 is the only place a failure can be read from
        outside the container. Four bound parameters, well inside D1's
        per-statement parameter ceiling -- and fixed, not scaled by row count.
        """
        self._d1.execute(
            "UPDATE versions SET index_state = ?, index_error = ?,"
            " index_state_at = ? WHERE id = ?",
            [state, error, time.time(), version_id],
        )

    def get_index_state(self, version_id: str) -> dict | None:
        """Return the indexing-attempt record for a version, or None."""
        row = self._d1.fetchone(
            "SELECT id, library_id, version, index_state, index_error,"
            " index_state_at, page_count, chunk_count FROM versions WHERE id = ?",
            [version_id],
        )
        if row is None or row.get("index_state") is None:
            return None
        return {
            "version_id": row["id"],
            "library_id": row["library_id"],
            "version": row["version"],
            "state": row["index_state"],
            "error": row["index_error"],
            "updated_at": row["index_state_at"],
            "page_count": row["page_count"],
            "chunk_count": row["chunk_count"],
        }

    def index_status(self, limit: int = 20) -> dict:
        """Summarize recorded indexing attempts. Mirrors DocsDB.index_status."""
        counts = {
            r["state"]: r["n"]
            for r in self._d1.execute(
                "SELECT index_state AS state, COUNT(*) AS n FROM versions"
                " WHERE index_state IS NOT NULL GROUP BY index_state",
                [],
            )
        }
        recent = [
            {
                "library": r["library"],
                "version": r["version"],
                "state": r["index_state"],
                "error": r["index_error"],
                "updated_at": r["index_state_at"],
                "page_count": r["page_count"],
                "chunk_count": r["chunk_count"],
            }
            for r in self._d1.execute(
                "SELECT v.version, v.index_state, v.index_error, v.index_state_at,"
                " v.page_count, v.chunk_count, l.name AS library"
                " FROM versions v LEFT JOIN libraries l ON v.library_id = l.id"
                " WHERE v.index_state IS NOT NULL"
                " ORDER BY v.index_state_at DESC LIMIT ?",
                [limit],
            )
        ]
        return {"counts": counts, "recent": recent}

    def mark_library_indexed(
        self, library_id: str, total_versions: int | None = None
    ) -> None:
        """Update libraries.last_indexed_at, and total_versions when given.

        DocsDB.mark_library_indexed probes pragma_table_info because a
        pre-Alembic SQLite file may lack these columns. D1's schema is owned by
        migrations/0001_init_wet.sql, which has both, so this writes fixed SQL
        with no column names assembled at runtime.
        """
        if total_versions is None:
            self._d1.execute(
                "UPDATE libraries SET last_indexed_at = ? WHERE id = ?",
                [time.time(), library_id],
            )
            return
        self._d1.execute(
            "UPDATE libraries SET last_indexed_at = ?, total_versions = ? WHERE id = ?",
            [time.time(), int(total_versions), library_id],
        )

    def mark_metadata_seeded(self, library_id: str) -> None:
        """Record a metadata-only seed pass (Tier 1 warmup freshness anchor).

        Deliberately separate from last_indexed_at so a seeded-but-unindexed
        library stays distinguishable from an indexed one. The column arrives
        in migrations/0002_project_context.sql.
        """
        self._d1.execute(
            "UPDATE libraries SET metadata_seeded_at = ? WHERE id = ?",
            [time.time(), library_id],
        )

    # --- project context (Cabinets isolation) ---

    def upsert_project_context(
        self, project_path: str, locked_libraries: list[dict]
    ) -> None:
        """Persist a project's locked-library set, preserving created_at."""
        now = time.time()
        payload = json.dumps(locked_libraries, ensure_ascii=False)
        existing = self._d1.fetchone(
            "SELECT created_at FROM project_context WHERE project_path = ?",
            [project_path],
        )
        if existing:
            self._d1.execute(
                "UPDATE project_context SET locked_libraries = ?, last_used_at = ?"
                " WHERE project_path = ?",
                [payload, now, project_path],
            )
            return
        self._d1.execute(
            "INSERT INTO project_context (project_path, locked_libraries,"
            " created_at, last_used_at) VALUES (?,?,?,?)",
            [project_path, payload, now, now],
        )

    def get_project_context(self, project_path: str) -> dict | None:
        """Return the lock entry for a project, or None if not locked."""
        row = self._d1.fetchone(
            "SELECT project_path, locked_libraries, created_at, last_used_at"
            " FROM project_context WHERE project_path = ?",
            [project_path],
        )
        if row is None:
            return None
        result = dict(row)
        try:
            libs = json.loads(result["locked_libraries"])
            if not isinstance(libs, list):
                libs = []
            result["locked_libraries"] = libs
        except (TypeError, json.JSONDecodeError) as e:
            # Same trade-off DocsDB.get_project_context documents: an unreadable
            # lock reads as "nothing locked", which is shaped exactly like a
            # project that was never locked, so it is logged rather than hidden.
            logger.warning(
                f"project_context row for {project_path!r} has unreadable "
                f"locked_libraries ({type(e).__name__}: {e}); treating the "
                "project as unlocked"
            )
            result["locked_libraries"] = []
        return result

    def touch_project_context(self, project_path: str) -> None:
        """Update last_used_at; call before each query that honors a lock."""
        self._d1.execute(
            "UPDATE project_context SET last_used_at = ? WHERE project_path = ?",
            [time.time(), project_path],
        )

    # --- lifecycle + file-based sync ---

    def close(self) -> None:
        """No handle to release: D1 and Vectorize are reached per request.

        DocsDB.close() ends a long-lived sqlite3 connection. D1Backend and
        VectorizeBackend hold nothing open between calls, so there is nothing
        here to close. server.py calls this during shutdown, so it returns
        quietly because there genuinely is no work -- not because a failure
        was swallowed.
        """

    def export_jsonl(self) -> str:
        raise NotImplementedError(
            "export_jsonl is not available on DOCS_DB_BACKEND=cf-d1. The store "
            "is Cloudflare D1 + Vectorize, already shared and durable across "
            "every instance, so there is no local docs.db to export and no "
            "second copy to keep in step. The GDrive/S3 DB-sync exists to move "
            "a single-machine SQLite file around and is redundant here (see "
            "docs/cf-template.md, 'Sync mode-gating'). Leave SYNC_ENABLED off "
            "on a cf-d1 deployment, or read the rows directly with "
            "`wrangler d1 execute`."
        )

    def import_jsonl(self, data: str, mode: str = "merge") -> dict:
        raise NotImplementedError(
            "import_jsonl is not available on DOCS_DB_BACKEND=cf-d1. Sync JSONL "
            "carries no embeddings -- export_jsonl drops them by design -- so "
            "every imported chunk would land in D1 with no matching vector in "
            "Vectorize. Those chunks would answer FTS queries while staying "
            "invisible to the vector arm of search(), i.e. a half-ranked index "
            "that looks like a working one. Index the library normally so "
            "chunks and embeddings are written together, or bulk-load D1 with "
            "`wrangler d1 execute` and re-embed."
        )

    # --- hybrid search (ranking pipeline reused from db.py) ---

    def search(
        self,
        query: str,
        library_name: str | None = None,
        version: str | None = None,
        limit: int = 10,
        query_embedding: list[float] | None = None,
    ) -> list[dict]:
        library_id = version_id = None
        if library_name:
            lib = self.get_library(library_name)
            if not lib:
                return []
            library_id = lib["id"]
            if version:
                ver = self.get_best_version(library_id, version)
                if ver:
                    version_id = ver["id"]

        candidate_limit = limit * 3
        fts_scores: dict[str, float] = {}
        fts_chunks: dict[str, dict] = {}

        for fts_query in _build_fts_queries(query):
            sql = (
                "SELECT c.*, l.name AS _library_name, "
                "bm25(doc_chunks_fts, 0.0, 2.0, 3.0, 2.0) AS bm25_score "
                "FROM doc_chunks_fts f JOIN doc_chunks c ON f.id = c.id "
                "LEFT JOIN libraries l ON c.library_id = l.id "
                "WHERE doc_chunks_fts MATCH ?"
            )
            params: list = [fts_query]
            if library_id:
                sql += " AND c.library_id = ?"
                params.append(library_id)
            if version_id:
                sql += " AND c.version_id = ?"
                params.append(version_id)
            sql += " ORDER BY bm25_score LIMIT ?"
            params.append(candidate_limit)
            for row in self._d1.execute(sql, params):
                cid = row["id"]
                score = -row.pop("bm25_score", 0)
                if cid not in fts_scores or score > fts_scores[cid]:
                    fts_scores[cid] = score
                    fts_chunks[cid] = row

        if fts_scores:
            mn, mx = min(fts_scores.values()), max(fts_scores.values())
            rng = mx - mn
            fts_scores = (
                {k: (v - mn) / rng for k, v in fts_scores.items()}
                if rng > 0
                else dict.fromkeys(fts_scores, 1.0)
            )

        vec_scores: dict[str, float] = {}
        if query_embedding:
            mfilter = {}
            if library_id:
                mfilter["library_id"] = library_id
            if version_id:
                mfilter["version_id"] = version_id
            vec_results = list(
                self._vec.query(
                    query_embedding,
                    top_k=min(candidate_limit, 50),
                    metadata_filter=mfilter or None,
                )
            )
            missing_ids = []
            for m in vec_results:
                cid = m["id"]
                vec_scores[cid] = max(0.0, float(m["score"]))
                if cid not in fts_chunks:
                    missing_ids.append(cid)

            if missing_ids:
                placeholders = ",".join(["?"] * len(missing_ids))
                sql = (
                    "SELECT c.*, l.name AS _library_name FROM doc_chunks c "
                    "LEFT JOIN libraries l ON c.library_id = l.id "
                    f"WHERE c.id IN ({placeholders})"
                )
                for row in self._d1.execute(sql, missing_ids):
                    fts_chunks[row["id"]] = row
                for cid in missing_ids:
                    if cid not in fts_chunks:
                        fts_chunks[cid] = {}

        scored = _combine_scores_cf(fts_scores, vec_scores, fts_chunks)
        return _build_results_cf(scored, fts_chunks, self._d1, limit)


def _combine_scores_cf(fts_scores, vec_scores, fts_chunks):
    """RRF k=60 + quality boost, identical formula to db.py DocsDB._combine_scores."""
    all_ids = fts_scores.keys() | vec_scores.keys()
    scored: list[tuple[str, float]] = []
    if vec_scores:
        k = 60
        fts_ranked = sorted(fts_scores, key=fts_scores.__getitem__, reverse=True)
        vec_ranked = sorted(vec_scores, key=vec_scores.__getitem__, reverse=True)
        fts_rank = {cid: i + 1 for i, cid in enumerate(fts_ranked)}
        vec_rank = {cid: i + 1 for i, cid in enumerate(vec_ranked)}
        default_rank = len(all_ids)
        for cid in all_ids:
            fr = fts_rank.get(cid, default_rank)
            vr = vec_rank.get(cid, default_rank)
            rrf = 1.0 / (k + fr) + 1.0 / (k + vr)
            chunk = fts_chunks.get(cid)
            quality = _chunk_quality_score(chunk["content"]) if chunk else 0.0
            scored.append((cid, rrf + quality * 0.005))
    else:
        for cid in fts_scores:
            chunk = fts_chunks.get(cid)
            quality = _chunk_quality_score(chunk["content"]) if chunk else 0.0
            scored.append((cid, fts_scores[cid] * 0.85 + quality * 0.15))
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored


def _build_results_cf(scored, fts_chunks, d1: D1Backend, limit: int):
    """URL diversity (2/url) + adjacent prefetch, ported from db.py L1172-1260."""
    max_per_url = 2
    url_counts: dict[str, int] = {}
    # batch-prefetch adjacent chunks from D1
    adj_keys: set[tuple[str, str, int]] = set()
    for cid, _ in scored:
        ch = fts_chunks.get(cid)
        if not ch:
            continue
        url, ver, idx = (
            ch.get("url", ""),
            ch.get("version_id", ""),
            ch.get("chunk_index", -1),
        )
        if url and ver and idx >= 0:
            adj_keys.add((url, ver, idx - 1))
            adj_keys.add((url, ver, idx + 1))
    adj_map: dict[tuple[str, str, int], str] = {}
    if adj_keys:
        unique_keys = sorted(adj_keys)
        batch_size = 100
        for i in range(0, len(unique_keys), batch_size):
            batch = unique_keys[i : i + batch_size]
            placeholders = ",".join(["(?,?,?)"] * len(batch))
            params = [v for k in batch for v in k]
            sql = (
                "SELECT url, version_id, chunk_index, content "
                "FROM doc_chunks WHERE (url, version_id, chunk_index) "
                f"IN (VALUES {placeholders})"
            )
            for row in d1.execute(sql, params):
                adj_map[(row["url"], row["version_id"], row["chunk_index"])] = row[
                    "content"
                ]

    results: list[dict] = []
    for cid, score in scored:
        if len(results) >= limit:
            break
        chunk = fts_chunks.get(cid)
        if not chunk:
            continue
        url = chunk.get("url", "")
        if url:
            url_counts[url] = url_counts.get(url, 0) + 1
            if url_counts[url] > max_per_url:
                continue
        result = {
            "content": chunk["content"],
            "title": chunk.get("title", ""),
            "url": url,
            "heading_path": chunk.get("heading_path", ""),
            "library": chunk.get("_library_name", ""),
            "score": round(score, 4),
            "topic": chunk.get("topic"),
            "section": chunk.get("section"),
            "token_count": chunk.get("token_count"),
            "version_id": chunk.get("version_id"),
        }
        idx, ver = chunk.get("chunk_index", -1), chunk.get("version_id", "")
        if url and ver and idx >= 0:
            if b := adj_map.get((url, ver, idx - 1)):
                result["context_before"] = b
            if a := adj_map.get((url, ver, idx + 1)):
                result["context_after"] = a
        results.append(result)
    return results
