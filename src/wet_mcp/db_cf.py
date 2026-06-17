"""Cloudflare docs DB: relational + FTS5 on D1, vectors on Vectorize.

Public interface mirrors wet_mcp.db.DocsDB (upsert_library / upsert_version /
get_library / get_best_version / add_chunks / search) so server.py is polymorphic.
The ranking pipeline (tiered FTS5, bm25 weights 0/2/3/2, RRF k=60, quality boost,
URL diversity 2/url, adjacent prefetch) is REUSED from db.py, not reimplemented.
"""

from __future__ import annotations

import time
import uuid

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

    def upsert_version(self, library_id: str, version: str) -> str:
        existing = self.get_best_version(library_id, version)
        if existing:
            return existing["id"]
        ver_id = str(uuid.uuid4())
        self._d1.execute(
            "INSERT INTO versions (id, library_id, version) VALUES (?,?,?)",
            [ver_id, library_id, version],
        )
        return ver_id

    def get_best_version(self, library_id: str, version: str | None) -> dict | None:
        if version:
            return self._d1.fetchone(
                "SELECT * FROM versions WHERE library_id = ? AND version = ?",
                [library_id, version],
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
                now,
            ]
            for c in chunks
        ]
        self._d1.executemany(
            "INSERT INTO doc_chunks (id, version_id, library_id, url, title, chunk_index,"
            " content, heading_path, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
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
            for m in self._vec.query(
                query_embedding,
                top_k=min(candidate_limit, 50),
                metadata_filter=mfilter or None,
            ):
                cid = m["id"]
                # cosine score already 0..1-ish
                vec_scores[cid] = max(0.0, float(m["score"]))
                if cid not in fts_chunks:
                    fts_chunks[cid] = (
                        self._d1.fetchone(
                            "SELECT c.*, l.name AS _library_name FROM doc_chunks c "
                            "LEFT JOIN libraries l ON c.library_id = l.id WHERE c.id = ?",
                            [cid],
                        )
                        or {}
                    )

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
    for url, ver, idx in adj_keys:
        row = d1.fetchone(
            "SELECT content FROM doc_chunks WHERE url = ? AND version_id = ? AND chunk_index = ?",
            [url, ver, idx],
        )
        if row:
            adj_map[(url, ver, idx)] = row["content"]

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
