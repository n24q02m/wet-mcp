-- migrations/0003_version_index_state.sql
-- Durable record of what the background indexer did, per (library, version).
--
-- Without it, `chunks: 0` in config(action="status") is one number covering
-- four different states -- never attempted, still running, failed, and
-- succeeded with no content -- and the failure path only ever wrote a
-- logger.error inside the Cloudflare container, where nothing collects it.
-- These three columns put the outcome where the normal query path can read
-- it, i.e. outside the container.
--
-- index_state is deliberately NOT the existing `status` column: `status`
-- gates what get_best_version serves, so a version must be able to stay
-- 'indexed' (still serving its old chunks) while its newest re-index attempt
-- reads 'failed'. page_count / chunk_count stay owned by mark_version_indexed
-- and keep describing the last SUCCESSFUL index.
--
-- Mirrors the SQLite side: db.py _create_versions_table + the
-- docs_006_version_index_state Alembic revision.
--
-- No transaction-control statements here: wrangler scans migration text for
-- them and refuses the file, matching on the raw text even inside a comment.

ALTER TABLE versions ADD COLUMN index_state TEXT;
ALTER TABLE versions ADD COLUMN index_error TEXT;
ALTER TABLE versions ADD COLUMN index_state_at REAL;
