## 2024-05-19: N+1 queries during data extraction in search
**Learning:** `DocsDB.search()` was executing a `SELECT name FROM libraries WHERE id = ?` within a loop over candidate chunks. This N+1 query created a performance bottleneck during search operations.
**Action:** Joined the `libraries` table in the initial FTS5 (`fts_sql`) and vector queries (`vec_sql` fallback) using `LEFT JOIN libraries l ON c.library_id = l.id`, retrieving `l.name AS library_name`. This avoids the loop-based database lookups and decreases latency (observed around 10% speed-up in benchmarks for multiple queries).
