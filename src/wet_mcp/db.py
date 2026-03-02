"""Persistent docs storage with hybrid search (FTS5 + optional sqlite-vec).

Stores library documentation chunks in SQLite with full-text search.
When an embedding model is configured, also stores vector embeddings
for semantic search with hybrid scoring.

Schema follows mnemo-mcp patterns: FTS5 content-sync mode with triggers,
sqlite-vec for vectors, JSONL export/import for sync.
"""

import json
import re
import sqlite3
import struct
import time
import uuid
from pathlib import Path

from loguru import logger

# Bump this when discovery scoring changes to invalidate stale caches.
from wet_mcp.sources.docs import DISCOVERY_VERSION


def _serialize_f32(vec: list[float]) -> bytes:
    """Serialize float vector for sqlite-vec."""
    return struct.pack(f"{len(vec)}f", *vec)


def _now_ts() -> float:
    """Current timestamp as float."""
    return time.time()


# Patterns for chunk quality scoring
_CODE_BLOCK_RE = re.compile(r"```")
_LINK_LINE_RE = re.compile(r"^\s*[-*]?\s*\[.+?\]\(.+?\)\s*$|^\s*https?://\S+\s*$")
# Function/class/type definitions (common across languages)
_DEF_RE = re.compile(
    r"^\s*(?:def |class |fn |func |function |interface |type |struct |enum |const |let |var |export )",
    re.MULTILINE,
)
# Docstring / doc comment patterns
_DOCSTRING_RE = re.compile(
    r'"""|\'\'\'|/\*\*|///|#\s+(?:Args|Returns|Raises|Example|Usage|Parameters|Note)'
)
# Directive-heavy content (mkdocs leftover, rst directives)
_DIRECTIVE_RE = re.compile(r"^(?:!!!|:::|\.\.)\s", re.MULTILINE)


def _build_fts_queries(query: str) -> list[str]:
    """Build tiered FTS5 queries: PHRASE -> AND -> OR.

    No stop-word filtering — BM25's IDF naturally down-weights common
    words (any language) and the PHRASE->AND->OR fallback ensures precision
    first, then recall.
    """
    words = [w.strip() for w in query.split() if w.strip()]
    safe = [w.replace('"', '""') for w in words]

    if not safe:
        return []
    if len(safe) == 1:
        return [f'"{safe[0]}"*']

    return [
        # Tier 0: PHRASE — exact phrase match (highest precision)
        '"' + " ".join(safe) + '"',
        # Tier 1: AND — all terms must appear
        " AND ".join(f'"{w}"*' for w in safe),
        # Tier 2: OR — any term matches (broadest fallback)
        " OR ".join(f'"{w}"*' for w in safe),
    ]


def _chunk_quality_score(content: str) -> float:
    """Score chunk content quality for docs ranking (0.0 to 1.0).

    Boosts chunks with code examples, function/class definitions, and
    docstrings. Penalizes link-heavy TOC chunks, directive-heavy content,
    and very short chunks.
    """
    score = 0.0

    # Code blocks signal practical documentation
    code_blocks = len(_CODE_BLOCK_RE.findall(content)) // 2
    score += min(code_blocks, 3) * 2.0  # up to +6

    # Function/class definitions signal API documentation
    defs = len(_DEF_RE.findall(content))
    score += min(defs, 4) * 1.5  # up to +6

    # Docstrings/doc comments signal well-documented code
    docstrings = len(_DOCSTRING_RE.findall(content))
    score += min(docstrings, 3) * 1.0  # up to +3

    # Longer content tends to be more informative
    length = len(content)
    if length > 500:
        score += 2.0
    elif length > 200:
        score += 1.0

    # Link-heavy content is usually navigation/TOC, not docs
    lines = [ln for ln in content.splitlines() if ln.strip()]
    if lines:
        link_lines = sum(1 for ln in lines if _LINK_LINE_RE.match(ln))
        ratio = link_lines / len(lines)
        if ratio > 0.5:
            score -= 4.0
        elif ratio > 0.3:
            score -= 2.0

    # Directive-heavy content (leftover mkdocs/rst noise)
    directives = len(_DIRECTIVE_RE.findall(content))
    if directives > 3:
        score -= 2.0
    elif directives > 1:
        score -= 1.0

    # Normalize to 0-1 range (wider range due to more signals)
    return max(0.0, min(score / 12.0, 1.0))


class DocsDB:
    """SQLite-backed docs storage with FTS5 hybrid search."""

    def __init__(self, db_path: Path, embedding_dims: int = 0):
        self._db_path = db_path
        self._embedding_dims = embedding_dims
        self._vec_enabled = False

        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(db_path))
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode = WAL")
        self._conn.execute("PRAGMA synchronous = NORMAL")
        self._conn.execute("PRAGMA busy_timeout = 5000")

        # Try loading sqlite-vec extension
        if embedding_dims > 0:
            try:
                import sqlite_vec

                self._conn.enable_load_extension(True)
                sqlite_vec.load(self._conn)
                self._conn.enable_load_extension(False)
                self._vec_enabled = True
                logger.debug("sqlite-vec extension loaded")
            except Exception as e:
                logger.debug(f"sqlite-vec not available, FTS-only mode: {e}")

        self._create_tables()
        logger.debug(f"DocsDB initialized at {db_path} (vec={self._vec_enabled})")

    def _create_tables(self) -> None:
        # Libraries metadata
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS libraries (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                docs_url TEXT,
                registry TEXT,
                description TEXT,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            )
        """)
        self._conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_libraries_name
            ON libraries(name)
        """)

        # Migration: add discovery_version column if missing
        try:
            self._conn.execute(
                "ALTER TABLE libraries ADD COLUMN discovery_version INTEGER DEFAULT 0"
            )
            self._conn.commit()
            logger.debug("Migrated libraries table: added discovery_version")
        except sqlite3.OperationalError:
            pass  # Column already exists

        # Versions
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS versions (
                id TEXT PRIMARY KEY,
                library_id TEXT NOT NULL,
                version TEXT NOT NULL DEFAULT 'latest',
                docs_url TEXT,
                indexed_at REAL,
                page_count INTEGER DEFAULT 0,
                chunk_count INTEGER DEFAULT 0,
                status TEXT DEFAULT 'pending',
                FOREIGN KEY (library_id) REFERENCES libraries(id) ON DELETE CASCADE,
                UNIQUE(library_id, version)
            )
        """)

        # Document chunks
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS doc_chunks (
                id TEXT PRIMARY KEY,
                version_id TEXT NOT NULL,
                library_id TEXT NOT NULL,
                url TEXT,
                title TEXT,
                chunk_index INTEGER NOT NULL DEFAULT 0,
                content TEXT NOT NULL,
                heading_path TEXT,
                created_at REAL NOT NULL,
                FOREIGN KEY (version_id) REFERENCES versions(id) ON DELETE CASCADE,
                FOREIGN KEY (library_id) REFERENCES libraries(id) ON DELETE CASCADE
            )
        """)
        self._conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_chunks_version
            ON doc_chunks(version_id)
        """)
        self._conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_chunks_library
            ON doc_chunks(library_id)
        """)
        self._conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_chunks_url_order
            ON doc_chunks(url, version_id, chunk_index)
        """)

        # FTS5 (content-sync mode)
        self._conn.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS doc_chunks_fts
            USING fts5(
                id UNINDEXED,
                content,
                title,
                heading_path,
                content=doc_chunks,
                content_rowid=rowid,
                tokenize='porter unicode61'
            )
        """)

        # FTS5 sync triggers
        self._conn.execute("""
            CREATE TRIGGER IF NOT EXISTS chunks_ai AFTER INSERT ON doc_chunks BEGIN
                INSERT INTO doc_chunks_fts(rowid, id, content, title, heading_path)
                VALUES (new.rowid, new.id, new.content, new.title, new.heading_path);
            END
        """)
        self._conn.execute("""
            CREATE TRIGGER IF NOT EXISTS chunks_ad AFTER DELETE ON doc_chunks BEGIN
                INSERT INTO doc_chunks_fts(doc_chunks_fts, rowid, id, content, title, heading_path)
                VALUES ('delete', old.rowid, old.id, old.content, old.title, old.heading_path);
            END
        """)
        self._conn.execute("""
            CREATE TRIGGER IF NOT EXISTS chunks_au AFTER UPDATE ON doc_chunks BEGIN
                INSERT INTO doc_chunks_fts(doc_chunks_fts, rowid, id, content, title, heading_path)
                VALUES ('delete', old.rowid, old.id, old.content, old.title, old.heading_path);
                INSERT INTO doc_chunks_fts(rowid, id, content, title, heading_path)
                VALUES (new.rowid, new.id, new.content, new.title, new.heading_path);
            END
        """)

        # Vector table (optional)
        if self._vec_enabled and self._embedding_dims > 0:
            row = self._conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='doc_chunks_vec'"
            ).fetchone()
            if not row:
                self._conn.execute(f"""
                    CREATE VIRTUAL TABLE doc_chunks_vec
                    USING vec0(
                        id TEXT PRIMARY KEY,
                        embedding float[{self._embedding_dims}]
                    )
                """)

        self._conn.commit()

    # -----------------------------------------------------------------------
    # Stats
    # -----------------------------------------------------------------------

    def stats(self) -> dict:
        """Return database statistics."""
        lib_count = self._conn.execute("SELECT COUNT(*) FROM libraries").fetchone()[0]
        chunk_count = self._conn.execute("SELECT COUNT(*) FROM doc_chunks").fetchone()[
            0
        ]
        return {
            "libraries": lib_count,
            "chunks": chunk_count,
            "vec_enabled": self._vec_enabled,
        }

    # -----------------------------------------------------------------------
    # Library CRUD
    # -----------------------------------------------------------------------

    def upsert_library(
        self,
        name: str,
        docs_url: str | None = None,
        registry: str | None = None,
        description: str | None = None,
    ) -> str:
        """Create or update a library. Returns library ID.

        Automatically stamps the current ``DISCOVERY_VERSION``.
        """
        now = _now_ts()
        # Normalize name to lowercase
        norm_name = name.lower().strip()

        row = self._conn.execute(
            "SELECT id FROM libraries WHERE name = ?", (norm_name,)
        ).fetchone()

        if row:
            lib_id = row["id"]
            updates = []
            params: list = []
            if docs_url is not None:
                updates.append("docs_url = ?")
                params.append(docs_url)
            if registry is not None:
                updates.append("registry = ?")
                params.append(registry)
            if description is not None:
                updates.append("description = ?")
                params.append(description)
            updates.append("discovery_version = ?")
            params.append(DISCOVERY_VERSION)
            updates.append("updated_at = ?")
            params.append(now)
            params.append(lib_id)
            if updates:
                self._conn.execute(
                    f"UPDATE libraries SET {', '.join(updates)} WHERE id = ?",
                    params,
                )
                self._conn.commit()
            return lib_id

        lib_id = uuid.uuid4().hex[:12]
        self._conn.execute(
            """INSERT INTO libraries
               (id, name, docs_url, registry, description, discovery_version,
                created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                lib_id,
                norm_name,
                docs_url,
                registry,
                description,
                DISCOVERY_VERSION,
                now,
                now,
            ),
        )
        self._conn.commit()
        return lib_id

    def get_library(self, name: str) -> dict | None:
        """Get library by name."""
        row = self._conn.execute(
            "SELECT * FROM libraries WHERE name = ?", (name.lower().strip(),)
        ).fetchone()
        return dict(row) if row else None

    def list_libraries(self) -> list[dict]:
        """List all libraries with chunk counts."""
        rows = self._conn.execute("""
            SELECT l.*,
                   COALESCE(SUM(v.chunk_count), 0) as total_chunks,
                   COUNT(v.id) as version_count
            FROM libraries l
            LEFT JOIN versions v ON v.library_id = l.id AND v.status = 'indexed'
            GROUP BY l.id
            ORDER BY l.name
        """).fetchall()
        return [dict(r) for r in rows]

    def remove_library(self, name: str) -> bool:
        """Remove a library and all its chunks."""
        lib = self.get_library(name)
        if not lib:
            return False

        lib_id = lib["id"]

        # Remove vector entries
        if self._vec_enabled:
            try:
                self._conn.execute(
                    "DELETE FROM doc_chunks_vec WHERE id IN (SELECT id FROM doc_chunks WHERE library_id = ?)",
                    (lib_id,),
                )
            except Exception:
                pass

        # Cascade deletes chunks and versions
        self._conn.execute("DELETE FROM doc_chunks WHERE library_id = ?", (lib_id,))
        self._conn.execute("DELETE FROM versions WHERE library_id = ?", (lib_id,))
        self._conn.execute("DELETE FROM libraries WHERE id = ?", (lib_id,))
        self._conn.commit()
        return True

    # -----------------------------------------------------------------------
    # Version management
    # -----------------------------------------------------------------------

    def upsert_version(
        self,
        library_id: str,
        version: str = "latest",
        docs_url: str | None = None,
    ) -> str:
        """Create or get version. Returns version ID."""
        row = self._conn.execute(
            "SELECT id FROM versions WHERE library_id = ? AND version = ?",
            (library_id, version),
        ).fetchone()

        if row:
            ver_id = row["id"]
            if docs_url:
                self._conn.execute(
                    "UPDATE versions SET docs_url = ? WHERE id = ?",
                    (docs_url, ver_id),
                )
                self._conn.commit()
            return ver_id

        ver_id = uuid.uuid4().hex[:12]
        self._conn.execute(
            """INSERT INTO versions (id, library_id, version, docs_url, status)
               VALUES (?, ?, ?, ?, 'pending')""",
            (ver_id, library_id, version, docs_url),
        )
        self._conn.commit()
        return ver_id

    def mark_version_indexed(
        self, version_id: str, page_count: int, chunk_count: int
    ) -> None:
        """Mark version as indexed with counts."""
        self._conn.execute(
            """UPDATE versions
               SET status = 'indexed', indexed_at = ?, page_count = ?, chunk_count = ?
               WHERE id = ?""",
            (_now_ts(), page_count, chunk_count, version_id),
        )
        self._conn.commit()

    def get_best_version(
        self, library_id: str, target: str | None = None
    ) -> dict | None:
        """Get best matching version for library."""
        if target:
            # Try exact match first
            row = self._conn.execute(
                """SELECT * FROM versions
                   WHERE library_id = ? AND version = ? AND status = 'indexed'""",
                (library_id, target),
            ).fetchone()
            if row:
                return dict(row)

        # Fallback to latest indexed
        row = self._conn.execute(
            """SELECT * FROM versions
               WHERE library_id = ? AND status = 'indexed'
               ORDER BY indexed_at DESC LIMIT 1""",
            (library_id,),
        ).fetchone()
        return dict(row) if row else None

    # -----------------------------------------------------------------------
    # Chunks CRUD
    # -----------------------------------------------------------------------

    def add_chunks(
        self,
        version_id: str,
        library_id: str,
        chunks: list[dict],
        embeddings: list[list[float]] | None = None,
    ) -> int:
        """Add document chunks with optional embeddings.

        Each chunk dict: {url, title, content, heading_path, chunk_index}
        """
        now = _now_ts()
        count = 0

        for i, chunk in enumerate(chunks):
            chunk_id = uuid.uuid4().hex[:12]
            self._conn.execute(
                """INSERT INTO doc_chunks
                   (id, version_id, library_id, url, title, chunk_index, content, heading_path, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    chunk_id,
                    version_id,
                    library_id,
                    chunk.get("url", ""),
                    chunk.get("title", ""),
                    chunk.get("chunk_index", i),
                    chunk["content"],
                    chunk.get("heading_path", ""),
                    now,
                ),
            )

            # Store embedding if available
            if (
                self._vec_enabled
                and embeddings
                and i < len(embeddings)
                and embeddings[i]
            ):
                try:
                    self._conn.execute(
                        "INSERT INTO doc_chunks_vec (id, embedding) VALUES (?, ?)",
                        (chunk_id, _serialize_f32(embeddings[i])),
                    )
                except Exception as e:
                    logger.debug(f"Failed to store embedding: {e}")

            count += 1

        self._conn.commit()
        return count

    def clear_version_chunks(self, version_id: str) -> int:
        """Remove all chunks for a version (before re-indexing)."""
        if self._vec_enabled:
            try:
                self._conn.execute(
                    "DELETE FROM doc_chunks_vec WHERE id IN (SELECT id FROM doc_chunks WHERE version_id = ?)",
                    (version_id,),
                )
            except Exception:
                pass

        cursor = self._conn.execute(
            "DELETE FROM doc_chunks WHERE version_id = ?", (version_id,)
        )
        self._conn.commit()
        return cursor.rowcount

    # -----------------------------------------------------------------------
    # Search
    # -----------------------------------------------------------------------

    def search(
        self,
        query: str,
        library_name: str | None = None,
        version: str | None = None,
        limit: int = 10,
        query_embedding: list[float] | None = None,
    ) -> list[dict]:
        """Hybrid search: FTS5 + optional vector + quality scoring.

        Uses tiered FTS5 queries (AND -> OR fallback), BM25 column weights
        (boosting title/heading matches), min-max score normalization,
        and RRF fusion when vector search is available.
        Recency is intentionally excluded -- all doc chunks share the same
        indexing timestamp, making recency meaningless for static docs.

        Args:
            query: Search query text
            library_name: Filter by library name
            version: Filter by version
            limit: Max results
            query_embedding: Optional embedding vector for semantic search

        Returns:
            List of chunk dicts sorted by relevance score
        """
        # Resolve library/version filters
        library_id = None
        version_id = None
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

        # --- FTS5 search with tiered queries + BM25 column weights ---
        # Weights: id(0), content(2), title(3), heading_path(2)
        # Flattened: content is the primary signal, title gets a moderate
        # boost, heading_path gets minimal boost (BM25 already naturally
        # up-weights matches in short fields via tf-idf).
        fts_queries = _build_fts_queries(query)
        fts_scores: dict[str, float] = {}
        fts_chunks: dict[str, dict] = {}

        for fts_query in fts_queries:
            try:
                fts_sql = """
                    SELECT c.*,
                           bm25(doc_chunks_fts, 0.0, 2.0, 3.0, 2.0) AS bm25_score
                    FROM doc_chunks_fts f
                    JOIN doc_chunks c ON f.id = c.id
                    WHERE doc_chunks_fts MATCH ?
                """
                fts_params: list = [fts_query]

                if library_id:
                    fts_sql += " AND c.library_id = ?"
                    fts_params.append(library_id)
                if version_id:
                    fts_sql += " AND c.version_id = ?"
                    fts_params.append(version_id)

                fts_sql += " ORDER BY bm25_score LIMIT ?"
                fts_params.append(candidate_limit)

                rows = self._conn.execute(fts_sql, fts_params).fetchall()
                if rows:
                    for row in rows:
                        chunk = dict(row)
                        cid = chunk["id"]
                        score = -chunk.pop("bm25_score", 0)
                        # Keep the best score across tiers (PHRASE > AND > OR)
                        if cid not in fts_scores or score > fts_scores[cid]:
                            fts_scores[cid] = score
                            fts_chunks[cid] = chunk
                    # Stop once we have enough candidates across all tiers
                    if len(fts_scores) >= candidate_limit:
                        break
            except Exception as e:
                logger.debug(f"FTS search error: {e}")
                continue

        # Min-max normalize FTS scores to 0-1
        if fts_scores:
            min_f = min(fts_scores.values())
            max_f = max(fts_scores.values())
            rng = max_f - min_f
            if rng > 0:
                fts_scores = {k: (v - min_f) / rng for k, v in fts_scores.items()}
            else:
                fts_scores = dict.fromkeys(fts_scores, 1.0)

        # --- Vector search ---
        vec_scores: dict[str, float] = {}
        if self._vec_enabled and query_embedding:
            try:
                vec_sql = """
                    SELECT v.id, v.distance
                    FROM doc_chunks_vec v
                    JOIN doc_chunks c ON v.id = c.id
                    WHERE v.embedding MATCH ?
                """
                vec_params: list = [_serialize_f32(query_embedding)]

                if library_id:
                    vec_sql += " AND c.library_id = ?"
                    vec_params.append(library_id)
                if version_id:
                    vec_sql += " AND c.version_id = ?"
                    vec_params.append(version_id)

                vec_sql += " ORDER BY v.distance LIMIT ?"
                vec_params.append(candidate_limit)

                vec_rows = self._conn.execute(vec_sql, vec_params).fetchall()
                for vr in vec_rows:
                    vec_scores[vr["id"]] = max(0.0, 1.0 - vr["distance"])

                    # Load chunk data if not already from FTS
                    if vr["id"] not in fts_chunks:
                        chunk_row = self._conn.execute(
                            "SELECT * FROM doc_chunks WHERE id = ?", (vr["id"],)
                        ).fetchone()
                        if chunk_row:
                            fts_chunks[vr["id"]] = dict(chunk_row)
            except Exception as e:
                logger.debug(f"Vector search error: {e}")

        # --- Combine scores ---
        all_ids = set(fts_scores.keys()) | set(vec_scores.keys())
        scored: list[tuple[str, float]] = []

        if vec_scores:
            # RRF fusion when both FTS and vector signals available
            k = 60
            fts_ranked = sorted(
                all_ids, key=lambda x: fts_scores.get(x, 0.0), reverse=True
            )
            vec_ranked = sorted(
                all_ids, key=lambda x: vec_scores.get(x, 0.0), reverse=True
            )
            fts_rank = {cid: i + 1 for i, cid in enumerate(fts_ranked)}
            vec_rank = {cid: i + 1 for i, cid in enumerate(vec_ranked)}

            for cid in all_ids:
                fr = fts_rank.get(cid, len(all_ids))
                vr = vec_rank.get(cid, len(all_ids))
                rrf = 1.0 / (k + fr) + 1.0 / (k + vr)
                # Small quality boost
                chunk = fts_chunks.get(cid)
                quality = _chunk_quality_score(chunk["content"]) if chunk else 0.0
                scored.append((cid, rrf + quality * 0.005))
        else:
            # FTS-only: normalized score + quality boost
            for cid in fts_scores:
                fts = fts_scores[cid]
                chunk = fts_chunks.get(cid)
                quality = _chunk_quality_score(chunk["content"]) if chunk else 0.0
                score = fts * 0.85 + quality * 0.15
                scored.append((cid, score))

        # Sort by score descending
        scored.sort(key=lambda x: x[1], reverse=True)

        # Build results with cross-chunk context + URL diversity limit
        # Cap results per URL to avoid returning 4-5 chunks from the same page
        max_per_url = 2
        url_counts: dict[str, int] = {}
        results = []
        for cid, score in scored:
            if len(results) >= limit:
                break
            chunk = fts_chunks.get(cid)
            if not chunk:
                continue
            chunk_url = chunk.get("url", "")
            if chunk_url:
                url_counts[chunk_url] = url_counts.get(chunk_url, 0) + 1
                if url_counts[chunk_url] > max_per_url:
                    continue

            # Resolve library name
            lib_row = self._conn.execute(
                "SELECT name FROM libraries WHERE id = ?", (chunk["library_id"],)
            ).fetchone()

            result: dict = {
                "content": chunk["content"],
                "title": chunk.get("title", ""),
                "url": chunk.get("url", ""),
                "heading_path": chunk.get("heading_path", ""),
                "library": lib_row["name"] if lib_row else "",
                "score": round(score, 4),
            }

            # Cross-chunk context: include adjacent chunks for better RAG
            chunk_url = chunk.get("url", "")
            chunk_idx = chunk.get("chunk_index", -1)
            ver_id_val = chunk.get("version_id", "")
            if chunk_url and ver_id_val and chunk_idx >= 0:
                prev = self._conn.execute(
                    "SELECT content FROM doc_chunks "
                    "WHERE url = ? AND version_id = ? AND chunk_index = ?",
                    (chunk_url, ver_id_val, chunk_idx - 1),
                ).fetchone()
                if prev:
                    result["context_before"] = prev["content"]

                nxt = self._conn.execute(
                    "SELECT content FROM doc_chunks "
                    "WHERE url = ? AND version_id = ? AND chunk_index = ?",
                    (chunk_url, ver_id_val, chunk_idx + 1),
                ).fetchone()
                if nxt:
                    result["context_after"] = nxt["content"]

            results.append(result)

        return results

    # -----------------------------------------------------------------------
    # Export / Import (JSONL for sync)
    # -----------------------------------------------------------------------

    def export_jsonl(self) -> str:
        """Export all docs data as JSONL for sync."""
        lines = []

        # Export libraries
        for row in self._conn.execute(
            "SELECT * FROM libraries ORDER BY name"
        ).fetchall():
            d = dict(row)
            d["_type"] = "library"
            lines.append(json.dumps(d, ensure_ascii=False))

        # Export versions
        for row in self._conn.execute(
            "SELECT * FROM versions ORDER BY library_id"
        ).fetchall():
            d = dict(row)
            d["_type"] = "version"
            lines.append(json.dumps(d, ensure_ascii=False))

        # Export chunks (without embeddings — re-generate on target)
        for row in self._conn.execute(
            "SELECT * FROM doc_chunks ORDER BY library_id, chunk_index"
        ).fetchall():
            d = dict(row)
            d["_type"] = "chunk"
            lines.append(json.dumps(d, ensure_ascii=False))

        return "\n".join(lines)

    def import_jsonl(self, data: str, mode: str = "merge") -> dict:
        """Import JSONL data. mode: merge (skip existing) or replace (clear first)."""
        stats = {"libraries": 0, "versions": 0, "chunks": 0, "skipped": 0}

        if mode == "replace":
            if self._vec_enabled:
                try:
                    self._conn.execute("DELETE FROM doc_chunks_vec")
                except Exception:
                    pass
            self._conn.execute("DELETE FROM doc_chunks")
            self._conn.execute("DELETE FROM versions")
            self._conn.execute("DELETE FROM libraries")

        for line in data.strip().split("\n"):
            if not line.strip():
                continue
            obj = json.loads(line)
            obj_type = obj.pop("_type", None)

            if obj_type == "library":
                existing = self._conn.execute(
                    "SELECT id FROM libraries WHERE id = ?", (obj["id"],)
                ).fetchone()
                if mode == "merge" and existing:
                    stats["skipped"] += 1
                    continue
                self._conn.execute(
                    """INSERT OR REPLACE INTO libraries
                       (id, name, docs_url, registry, description, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (
                        obj["id"],
                        obj["name"],
                        obj.get("docs_url"),
                        obj.get("registry"),
                        obj.get("description"),
                        obj["created_at"],
                        obj["updated_at"],
                    ),
                )
                stats["libraries"] += 1

            elif obj_type == "version":
                existing = self._conn.execute(
                    "SELECT id FROM versions WHERE id = ?", (obj["id"],)
                ).fetchone()
                if mode == "merge" and existing:
                    stats["skipped"] += 1
                    continue
                self._conn.execute(
                    """INSERT OR REPLACE INTO versions
                       (id, library_id, version, docs_url, indexed_at, page_count, chunk_count, status)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        obj["id"],
                        obj["library_id"],
                        obj["version"],
                        obj.get("docs_url"),
                        obj.get("indexed_at"),
                        obj.get("page_count", 0),
                        obj.get("chunk_count", 0),
                        obj.get("status", "indexed"),
                    ),
                )
                stats["versions"] += 1

            elif obj_type == "chunk":
                existing = self._conn.execute(
                    "SELECT id FROM doc_chunks WHERE id = ?", (obj["id"],)
                ).fetchone()
                if mode == "merge" and existing:
                    stats["skipped"] += 1
                    continue
                self._conn.execute(
                    """INSERT OR REPLACE INTO doc_chunks
                       (id, version_id, library_id, url, title, chunk_index, content, heading_path, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        obj["id"],
                        obj["version_id"],
                        obj["library_id"],
                        obj.get("url", ""),
                        obj.get("title", ""),
                        obj.get("chunk_index", 0),
                        obj["content"],
                        obj.get("heading_path", ""),
                        obj["created_at"],
                    ),
                )
                stats["chunks"] += 1

        self._conn.commit()
        return stats

    def close(self) -> None:
        """Close database connection."""
        try:
            self._conn.close()
        except Exception:
            pass
