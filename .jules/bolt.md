## 2026-05-28 - Memory-efficient SQL Export/Import

**Learning:** Using `.fetchall()` on SQLite cursors for large datasets (like document chunks) causes high memory spikes. Direct iteration over the cursor in a generator, combined with `"\n".join()`, significantly reduces peak memory usage while maintaining performance. In `import_jsonl`, using `splitlines()` is slightly more robust than manual `split("\n")` for line-based processing of strings.

**Action:** Prefer streaming generators for database exports and avoid large intermediate list allocations for line-based string processing.
