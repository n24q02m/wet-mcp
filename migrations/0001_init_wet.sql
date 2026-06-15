-- migrations/0001_init_wet.sql
-- wet-mcp Cloudflare D1 schema. Ports SQLite DocsDB (db.py L462-555) verbatim
-- so D1 FTS5/bm25 ranking matches the local baseline.

CREATE TABLE IF NOT EXISTS libraries (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  docs_url TEXT,
  registry TEXT,
  description TEXT,
  canonical_name TEXT,
  homepage TEXT,
  github_url TEXT,
  package_managers TEXT,
  tier INTEGER NOT NULL DEFAULT 2,
  last_indexed_at REAL,
  total_versions INTEGER NOT NULL DEFAULT 0,
  discovery_version INTEGER DEFAULT 0,
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_libraries_name ON libraries(name);

CREATE TABLE IF NOT EXISTS versions (
  id TEXT PRIMARY KEY,
  library_id TEXT NOT NULL,
  version TEXT NOT NULL DEFAULT 'latest',
  docs_url TEXT,
  indexed_at REAL,
  page_count INTEGER DEFAULT 0,
  chunk_count INTEGER DEFAULT 0,
  status TEXT DEFAULT 'pending',
  release_date REAL,
  source_url TEXT,
  FOREIGN KEY (library_id) REFERENCES libraries(id) ON DELETE CASCADE,
  UNIQUE (library_id, version)
);

CREATE TABLE IF NOT EXISTS doc_chunks (
  id TEXT PRIMARY KEY,
  version_id TEXT NOT NULL,
  library_id TEXT NOT NULL,
  url TEXT,
  title TEXT,
  chunk_index INTEGER NOT NULL DEFAULT 0,
  content TEXT NOT NULL,
  heading_path TEXT,
  section TEXT,
  topic TEXT,
  content_hash TEXT,
  token_count INTEGER,
  created_at REAL NOT NULL,
  FOREIGN KEY (version_id) REFERENCES versions(id) ON DELETE CASCADE,
  FOREIGN KEY (library_id) REFERENCES libraries(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_chunks_version ON doc_chunks(version_id);
CREATE INDEX IF NOT EXISTS idx_chunks_ver_url_idx ON doc_chunks(version_id, url, chunk_index);
CREATE INDEX IF NOT EXISTS idx_chunks_library ON doc_chunks(library_id);
CREATE INDEX IF NOT EXISTS idx_chunks_url_order ON doc_chunks(url, version_id, chunk_index);
CREATE INDEX IF NOT EXISTS idx_doc_chunks_lib_ver_topic ON doc_chunks(library_id, version_id, topic);

CREATE VIRTUAL TABLE IF NOT EXISTS doc_chunks_fts USING fts5(
  id UNINDEXED,
  content,
  title,
  heading_path,
  content=doc_chunks,
  content_rowid=rowid,
  tokenize='porter unicode61'
);

CREATE TRIGGER IF NOT EXISTS chunks_ai AFTER INSERT ON doc_chunks BEGIN
  INSERT INTO doc_chunks_fts(rowid, id, content, title, heading_path)
  VALUES (new.rowid, new.id, new.content, new.title, new.heading_path);
END;

CREATE TRIGGER IF NOT EXISTS chunks_ad AFTER DELETE ON doc_chunks BEGIN
  INSERT INTO doc_chunks_fts(doc_chunks_fts, rowid, id, content, title, heading_path)
  VALUES ('delete', old.rowid, old.id, old.content, old.title, old.heading_path);
END;

CREATE TRIGGER IF NOT EXISTS chunks_au AFTER UPDATE ON doc_chunks BEGIN
  INSERT INTO doc_chunks_fts(doc_chunks_fts, rowid, id, content, title, heading_path)
  VALUES ('delete', old.rowid, old.id, old.content, old.title, old.heading_path);
  INSERT INTO doc_chunks_fts(rowid, id, content, title, heading_path)
  VALUES (new.rowid, new.id, new.content, new.title, new.heading_path);
END;

CREATE TABLE IF NOT EXISTS store_meta (
  key TEXT PRIMARY KEY,
  value TEXT
);
