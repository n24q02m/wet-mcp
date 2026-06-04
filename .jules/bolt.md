## 2025-05-15 - Redundant DB table info fetch
**Learning:** Repeatedly querying `PRAGMA table_info` for schema detection in SQLite can be optimized by caching column names at the instance level.
**Action:** Use a private helper method like `_get_table_columns(table_name)` with an internal `_table_columns` cache to avoid redundant schema lookups in methods called frequently during indexing or updates.
