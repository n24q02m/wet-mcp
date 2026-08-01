"""Abstract base class for docs-sync backends (Phase 2).

Each backend (gdrive, s3, ...) implements the same four-method contract so
the sync orchestrator can push the docs.db file, pull it back on a fresh
machine, and probe health uniformly.

wet-mcp's docs.db is a non-sensitive SQLite cache of indexed open-source
documentation - unlike mnemo-mcp's memory passport, no AES-256-GCM bundle
encryption is required. The file is pushed / pulled directly.

Spec reference: parity refactor with ``mnemo-mcp/sync/base.py``.
"""

from __future__ import annotations

import asyncio
import sqlite3
from abc import ABC, abstractmethod
from pathlib import Path

from loguru import logger


async def checkpoint_wal(db_path: Path) -> None:
    """Fold the ``-wal`` sidecar back into ``db_path`` before an upload.

    :class:`~wet_mcp.db.DocsDB` opens SQLite with ``PRAGMA journal_mode =
    WAL``, so recent commits -- and, on a young database, the whole schema
    -- live in ``<db_path>-wal`` until SQLite checkpoints. Every backend
    uploads the main ``.db`` file only (that is the contract below: all
    sync state lives in the local SQLite file on disk), so skipping this
    step can publish a valid-but-EMPTY database to the remote.

    ``TRUNCATE`` is the right level here. ``PASSIVE`` gives up as soon as
    any reader is active and can transfer nothing; ``FULL`` transfers all
    frames but leaves the sidecar in place, so a partially-reclaimed WAL
    keeps growing across ticks. ``TRUNCATE`` transfers every frame AND
    resets the sidecar to zero length, which is exactly the "main file is
    complete" invariant the upload needs.

    Failures are logged, never raised: the main ``.db`` file is always a
    self-consistent SQLite database, so pushing a slightly stale snapshot
    is strictly better than crashing the background sync loop.
    """
    if not db_path.exists():
        return

    def _checkpoint() -> tuple | None:
        conn = sqlite3.connect(str(db_path))
        try:
            conn.execute("PRAGMA busy_timeout = 5000")
            return conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
        finally:
            conn.close()

    try:
        row = await asyncio.to_thread(_checkpoint)
    except sqlite3.Error as e:
        logger.warning(f"WAL checkpoint failed for {db_path}: {e}")
        return

    # Row is (busy, wal_pages, checkpointed_pages); busy != 0 means another
    # connection held a lock and some frames stayed behind.
    if row is not None and row[0] != 0:
        logger.warning(
            f"WAL checkpoint busy for {db_path} (result={tuple(row)}); "
            "the uploaded snapshot may lag the newest commits"
        )


class SyncBackend(ABC):
    """Contract every docs-sync backend must satisfy.

    Implementations should be stateless beyond connection / OAuth objects -
    all sync state lives in the local SQLite docs.db on disk.
    """

    #: Stable identifier registered into :func:`wet_mcp.sync.register`.
    name: str = ""

    @abstractmethod
    async def push(self, db_path: Path) -> bool:
        """Upload the local ``db_path`` to the remote.

        Returns True on success, False on recoverable failure (the
        orchestrator logs + continues). Backends MUST raise only on
        programmer errors (bad config) so transient remote outages do
        not propagate as exceptions.
        """

    @abstractmethod
    async def pull(self, db_path: Path) -> Path | None:
        """Download the remote docs.db to a temp path next to ``db_path``.

        Returns the temp path on success, or ``None`` when the remote
        has no docs.db yet (fresh backend state) or pull failed.
        Callers are responsible for cleaning the temp file after merge.
        """

    @abstractmethod
    async def health_check(self) -> bool:
        """Cheap probe used by ``config(action="status")`` and CI smoke tests."""

    @property
    @abstractmethod
    def supports_oauth_setup(self) -> bool:
        """Whether this backend exposes an interactive OAuth setup flow.

        ``True`` for GDrive (Device Code via relay form), ``False`` for
        S3 (operator pre-provisions credentials at deploy time).
        """
