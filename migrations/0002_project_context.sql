-- migrations/0002_project_context.sql
-- Closes two gaps between migrations/0001_init_wet.sql and the SQLite DocsDB
-- schema in db.py, both of which a DocsDBCfBackend method needs:
--   1. project_context -- db.py _create_project_context_table (Cabinets project
--      isolation). upsert/get/touch_project_context read and write it.
--   2. libraries.metadata_seeded_at -- db.py _create_libraries_table.
--      mark_metadata_seeded writes it so a Tier-1 metadata seed stays
--      distinguishable from a real index.
-- doc_chunks_vec stays absent on purpose: D1 cannot load the sqlite-vec
-- extension, so vectors live in Vectorize instead.
--
-- No transaction-control statements here: wrangler scans migration text for
-- them and refuses the file, matching on the raw text even inside a comment.

CREATE TABLE IF NOT EXISTS project_context (
  project_path TEXT PRIMARY KEY,
  locked_libraries TEXT NOT NULL,
  created_at REAL NOT NULL,
  last_used_at REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_project_context_last_used
  ON project_context(last_used_at);

ALTER TABLE libraries ADD COLUMN metadata_seeded_at REAL;
