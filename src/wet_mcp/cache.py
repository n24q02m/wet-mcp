"""TTL-based cache for web operations (search, extract, crawl, map).

Uses SQLite for persistence across restarts. Cache entries expire based
on configurable TTL per action type. Thread-safe via WAL mode.

Cache is transparent - callers use ``get``/``set`` and the cache handles
expiry automatically. Old entries are purged periodically.
"""

import hashlib
import json
import sqlite3
import time
from pathlib import Path

from loguru import logger

# Default TTL per action (seconds)
_DEFAULT_TTLS: dict[str, int] = {
    "search": 3600,  # 1 hour
    "research": 3600,  # 1 hour
    "extract": 86400,  # 1 day
    "crawl": 86400,  # 1 day
    "map": 86400,  # 1 day
}

# Purge expired entries every N operations
_PURGE_INTERVAL = 50


def _cache_key(action: str, params: dict) -> str:
    """Generate a deterministic cache key from action + params."""
    # Sort keys for deterministic hashing
    raw = json.dumps({"action": action, **params}, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode()).hexdigest()


class WebCache:
    """SQLite-backed TTL cache for web operations."""

    def __init__(self, db_path: Path, ttls: dict[str, int] | None = None):
        self._db_path = db_path
        self._ttls = {**_DEFAULT_TTLS, **(ttls or {})}
        self._op_count = 0

        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(db_path))
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode = WAL")
        self._conn.execute("PRAGMA synchronous = NORMAL")
        self._conn.execute("PRAGMA busy_timeout = 5000")

        self._create_tables()
        logger.debug(f"WebCache initialized at {db_path}")

    def _create_tables(self) -> None:
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS web_cache (
                key TEXT PRIMARY KEY,
                action TEXT NOT NULL,
                params TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at REAL NOT NULL,
                expires_at REAL NOT NULL,
                hit_count INTEGER NOT NULL DEFAULT 0
            )
        """)
        self._conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_web_cache_expires
            ON web_cache(expires_at)
        """)
        self._conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_web_cache_action
            ON web_cache(action)
        """)
        self._conn.commit()

    def get(self, action: str, params: dict) -> str | None:
        """Get cached result if exists and not expired."""
        key = _cache_key(action, params)
        now = time.time()

        row = self._conn.execute(
            "SELECT content FROM web_cache WHERE key = ? AND expires_at > ?",
            (key, now),
        ).fetchone()

        if row:
            self._conn.execute(
                "UPDATE web_cache SET hit_count = hit_count + 1 WHERE key = ?",
                (key,),
            )
            self._conn.commit()
            logger.debug(f"Cache HIT: {action} ({key[:12]}...)")
            return row["content"]

        logger.debug(f"Cache MISS: {action} ({key[:12]}...)")
        return None

    def set(self, action: str, params: dict, content: str) -> None:
        """Store result in cache with TTL."""
        key = _cache_key(action, params)
        now = time.time()
        ttl = self._ttls.get(action, 3600)
        expires_at = now + ttl

        self._conn.execute(
            """INSERT OR REPLACE INTO web_cache
               (key, action, params, content, created_at, expires_at, hit_count)
               VALUES (?, ?, ?, ?, ?, ?, 0)""",
            (key, action, json.dumps(params, sort_keys=True), content, now, expires_at),
        )
        self._conn.commit()
        logger.debug(f"Cache SET: {action} ({key[:12]}...) TTL={ttl}s")

        # Periodic purge
        self._op_count += 1
        if self._op_count >= _PURGE_INTERVAL:
            self._purge_expired()
            self._op_count = 0

    def get_extract(self, url: str) -> str | None:
        """Get cached extract result for a single URL.

        This enables docs action to reuse already-extracted content
        without re-crawling.
        """
        # Check extract cache with url in params
        for action in ("extract", "crawl"):
            row = self._conn.execute(
                """SELECT content FROM web_cache
                   WHERE action = ? AND expires_at > ?
                   AND params LIKE ?
                   LIMIT 1""",
                (action, time.time(), f'%"{url}"%'),
            ).fetchone()
            if row:
                logger.debug(f"Extract cache HIT for URL: {url[:60]}...")
                return row["content"]
        return None

    def _purge_expired(self) -> None:
        """Remove expired cache entries."""
        cursor = self._conn.execute(
            "DELETE FROM web_cache WHERE expires_at <= ?",
            (time.time(),),
        )
        if cursor.rowcount > 0:
            self._conn.commit()
            logger.debug(f"Purged {cursor.rowcount} expired cache entries")

    def clear(self, action: str | None = None) -> int:
        """Clear cache entries. If action specified, only clear that action."""
        if action:
            cursor = self._conn.execute(
                "DELETE FROM web_cache WHERE action = ?", (action,)
            )
        else:
            cursor = self._conn.execute("DELETE FROM web_cache")
        self._conn.commit()
        return cursor.rowcount

    def stats(self) -> dict:
        """Get cache statistics."""
        now = time.time()
        rows = self._conn.execute(
            """
            SELECT action,
                   COUNT(*) as total,
                   SUM(CASE WHEN expires_at > ? THEN 1 ELSE 0 END) as active,
                   SUM(hit_count) as total_hits
            FROM web_cache
            GROUP BY action
        """,
            (now,),
        ).fetchall()

        return {
            row["action"]: {
                "total": row["total"],
                "active": row["active"],
                "hits": row["total_hits"],
            }
            for row in rows
        }

    def close(self) -> None:
        """Close database connection."""
        try:
            self._conn.close()
        except Exception:
            pass
