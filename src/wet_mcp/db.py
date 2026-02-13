"""Persistent docs storage with hybrid search (FTS5 + optional sqlite-vec).

Stores library documentation chunks in SQLite with full-text search.
When an embedding model is configured, also stores vector embeddings
for semantic search with hybrid scoring.

Schema follows mnemo-mcp patterns: FTS5 content-sync mode with triggers,
sqlite-vec for vectors, JSONL export/import for sync.
"""

import json
import sqlite3
import struct
import time
import uuid
from pathlib import Path

from loguru import logger


def _serialize_f32(vec: list[float]) -> bytes:
    """Serialize float vector for sqlite-vec."""
    return struct.pack(f"{len(vec)}f", *vec)


def _now_ts() -> float:
    """Current timestamp as float."""
    return time.time()


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
    # Library CRUD
    # -----------------------------------------------------------------------

    def upsert_library(
        self,
        name: str,
        docs_url: str | None = None,
        registry: str | None = None,
        description: str | None = None,
    ) -> str:
        """Create or update a library. Returns library ID."""
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
            """INSERT INTO libraries (id, name, docs_url, registry, description, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (lib_id, norm_name, docs_url, registry, description, now, now),
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
            chunk_ids = [
                r["id"]
                for r in self._conn.execute(
                    "SELECT id FROM doc_chunks WHERE library_id = ?", (lib_id,)
                ).fetchall()
            ]
            for cid in chunk_ids:
                try:
                    self._conn.execute(
                        "DELETE FROM doc_chunks_vec WHERE id = ?", (cid,)
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
            chunk_ids = [
                r["id"]
                for r in self._conn.execute(
                    "SELECT id FROM doc_chunks WHERE version_id = ?", (version_id,)
                ).fetchall()
            ]
            for cid in chunk_ids:
                try:
                    self._conn.execute(
                        "DELETE FROM doc_chunks_vec WHERE id = ?", (cid,)
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
        """Hybrid search: FTS5 + optional vector + recency scoring.

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

        # --- FTS5 search ---
        words = [w.strip() for w in query.split() if w.strip()]
        safe_words = [w.replace('"', '""') for w in words]
        fts_query = " OR ".join(f'"{w}"*' for w in safe_words)

        fts_scores: dict[str, float] = {}
        fts_chunks: dict[str, dict] = {}

        try:
            fts_sql = """
                SELECT c.*, f.rank
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

            fts_sql += " ORDER BY f.rank LIMIT ?"
            fts_params.append(limit * 3)

            rows = self._conn.execute(fts_sql, fts_params).fetchall()
            for row in rows:
                chunk = dict(row)
                cid = chunk["id"]
                fts_scores[cid] = 1.0 / (1.0 + abs(chunk.pop("rank", 0)))
                fts_chunks[cid] = chunk
        except Exception as e:
            logger.debug(f"FTS search error: {e}")

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
                vec_params.append(limit * 3)

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
        now_ts = time.time()

        for cid in all_ids:
            fts = fts_scores.get(cid, 0.0)
            vec = vec_scores.get(cid, 0.0)

            # Recency boost (exponential decay, half-life = 30 days)
            chunk = fts_chunks.get(cid)
            recency = 0.0
            if chunk:
                created = chunk.get("created_at", 0)
                if created:
                    days_old = (now_ts - created) / 86400
                    recency = 2.0 ** (-days_old / 30.0)

            # Weighted combination (matching mnemo-mcp pattern)
            if vec > 0:
                score = fts * 0.35 + vec * 0.35 + recency * 0.3
            else:
                score = fts * 0.6 + recency * 0.4

            scored.append((cid, score))

        # Sort by score descending
        scored.sort(key=lambda x: x[1], reverse=True)

        # Build results
        results = []
        for cid, score in scored[:limit]:
            chunk = fts_chunks.get(cid)
            if not chunk:
                continue

            # Resolve library name
            lib_row = self._conn.execute(
                "SELECT name FROM libraries WHERE id = ?", (chunk["library_id"],)
            ).fetchone()

            results.append(
                {
                    "content": chunk["content"],
                    "title": chunk.get("title", ""),
                    "url": chunk.get("url", ""),
                    "heading_path": chunk.get("heading_path", ""),
                    "library": lib_row["name"] if lib_row else "",
                    "score": round(score, 4),
                }
            )

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
