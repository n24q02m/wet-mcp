"""Extend libraries / versions / doc_chunks per spec §5.4.

Adds the Phase 2 Context7-level docs search columns:

* ``libraries``: ``canonical_name``, ``homepage``, ``github_url``,
  ``package_managers``, ``tier``, ``last_indexed_at``, ``total_versions``.
* ``versions``: ``release_date``, ``source_url``.
* ``doc_chunks``: ``section``, ``topic``, ``content_hash``, ``token_count``
  + composite index ``idx_doc_chunks_lib_ver_topic``.

The migration is *idempotent*: it inspects ``PRAGMA table_info(...)`` and
only adds columns / indexes that do not already exist. Pre-existing
``libraries`` rows are backfilled so:

* ``canonical_name = name``
* ``last_indexed_at = updated_at`` (best-effort recency anchor)
* ``tier`` defaults to 2 (on-demand) — Tier 1 warmup will explicitly
  upgrade curated entries to ``tier = 1``.

SQLite cannot drop columns without a table rebuild, so ``downgrade`` is a
no-op with a logged warning. The new columns are nullable / defaulted and
harmless to leave in place if rolling back to baseline.

Revision ID: docs_002_libraries
Revises: docs_001_baseline
Create Date: 2026-05-10
"""

from __future__ import annotations

import logging

from alembic import op

# Revision identifiers used by Alembic.
revision = "docs_002_libraries"
down_revision = "docs_001_baseline"
branch_labels = None
depends_on = None


logger = logging.getLogger("alembic.runtime.migration")


_TABLE_ALLOWLIST = {"libraries", "versions", "doc_chunks"}


def _existing_columns(table: str) -> set[str]:
    if table not in _TABLE_ALLOWLIST:
        raise ValueError(f"Unauthorized table: {table}")
    bind = op.get_bind()
    rows = bind.exec_driver_sql(f"PRAGMA table_info('{table}')").fetchall()
    return {row[1] for row in rows}


def _existing_indexes(table: str) -> set[str]:
    if table not in _TABLE_ALLOWLIST:
        raise ValueError(f"Unauthorized table: {table}")
    bind = op.get_bind()
    rows = bind.exec_driver_sql(f"PRAGMA index_list('{table}')").fetchall()
    return {row[1] for row in rows}


def upgrade() -> None:
    """Add Phase 2 columns idempotently + backfill key fields."""
    # libraries
    lib_cols = _existing_columns("libraries")
    if "discovery_version" not in lib_cols:
        op.execute("ALTER TABLE libraries ADD COLUMN discovery_version INTEGER DEFAULT 0")
    else:
        logger.info("docs_002: libraries.discovery_version already present, skipping")

    if "canonical_name" not in lib_cols:
        op.execute("ALTER TABLE libraries ADD COLUMN canonical_name TEXT")
    else:
        logger.info("docs_002: libraries.canonical_name already present, skipping")

    if "homepage" not in lib_cols:
        op.execute("ALTER TABLE libraries ADD COLUMN homepage TEXT")
    else:
        logger.info("docs_002: libraries.homepage already present, skipping")

    if "github_url" not in lib_cols:
        op.execute("ALTER TABLE libraries ADD COLUMN github_url TEXT")
    else:
        logger.info("docs_002: libraries.github_url already present, skipping")

    if "package_managers" not in lib_cols:
        op.execute("ALTER TABLE libraries ADD COLUMN package_managers TEXT")
    else:
        logger.info("docs_002: libraries.package_managers already present, skipping")

    if "tier" not in lib_cols:
        op.execute("ALTER TABLE libraries ADD COLUMN tier INTEGER NOT NULL DEFAULT 2")
    else:
        logger.info("docs_002: libraries.tier already present, skipping")

    if "last_indexed_at" not in lib_cols:
        op.execute("ALTER TABLE libraries ADD COLUMN last_indexed_at REAL")
    else:
        logger.info("docs_002: libraries.last_indexed_at already present, skipping")

    if "total_versions" not in lib_cols:
        op.execute("ALTER TABLE libraries ADD COLUMN total_versions INTEGER NOT NULL DEFAULT 0")
    else:
        logger.info("docs_002: libraries.total_versions already present, skipping")

    # Backfill canonical_name + last_indexed_at for pre-existing rows.
    op.execute(
        "UPDATE libraries SET canonical_name = name WHERE canonical_name IS NULL"
    )
    op.execute(
        "UPDATE libraries SET last_indexed_at = updated_at "
        "WHERE last_indexed_at IS NULL"
    )

    # versions
    ver_cols = _existing_columns("versions")
    if "release_date" not in ver_cols:
        op.execute("ALTER TABLE versions ADD COLUMN release_date REAL")
    else:
        logger.info("docs_002: versions.release_date already present, skipping")

    if "source_url" not in ver_cols:
        op.execute("ALTER TABLE versions ADD COLUMN source_url TEXT")
    else:
        logger.info("docs_002: versions.source_url already present, skipping")

    # doc_chunks
    chunk_cols = _existing_columns("doc_chunks")
    if "section" not in chunk_cols:
        op.execute("ALTER TABLE doc_chunks ADD COLUMN section TEXT")
    else:
        logger.info("docs_002: doc_chunks.section already present, skipping")

    if "topic" not in chunk_cols:
        op.execute("ALTER TABLE doc_chunks ADD COLUMN topic TEXT")
    else:
        logger.info("docs_002: doc_chunks.topic already present, skipping")

    if "content_hash" not in chunk_cols:
        op.execute("ALTER TABLE doc_chunks ADD COLUMN content_hash TEXT")
    else:
        logger.info("docs_002: doc_chunks.content_hash already present, skipping")

    if "token_count" not in chunk_cols:
        op.execute("ALTER TABLE doc_chunks ADD COLUMN token_count INTEGER")
    else:
        logger.info("docs_002: doc_chunks.token_count already present, skipping")

    if "idx_doc_chunks_lib_ver_topic" not in _existing_indexes("doc_chunks"):
        op.execute(
            "CREATE INDEX idx_doc_chunks_lib_ver_topic "
            "ON doc_chunks(library_id, version_id, topic)"
        )


def downgrade() -> None:
    """SQLite cannot drop columns without rebuilding the table.

    The new columns are nullable / defaulted and harmless to leave in place.
    """
    logger.warning(
        "docs_002 downgrade is a no-op: SQLite drop-column requires manual "
        "table rebuild. Phase 2 libraries / versions / doc_chunks columns "
        "left in place."
    )
