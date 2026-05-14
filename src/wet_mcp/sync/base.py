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

from abc import ABC, abstractmethod
from pathlib import Path


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
