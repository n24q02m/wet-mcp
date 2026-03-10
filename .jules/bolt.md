## 2026-03-08 - Atomic Cache Lookups
**Learning:** In SQLite >= 3.35.0, you can combine separate read-then-write operations into a single atomic query using the UPDATE ... RETURNING clause. This cuts database operations in half and eliminates race conditions.
**Action:** Look for read-modify-write patterns and consider using RETURNING to make them atomic.
