## 2024-03-24 - SQL Injection in _get_existing batch check
**Vulnerability:** SQL Injection in `src/wet_mcp/db.py` within the `_get_existing` function, caused by using an f-string to inject the `table` argument directly into a raw `SELECT id FROM {table}` query.
**Learning:** Even internal helper functions used during data import (like JSONL syncing) can become dangerous vectors if they dynamically construct queries without validating table names against an expected allowlist.
**Prevention:** Always validate dynamic table names against a strict allowlist (e.g., `if table not in {"libraries", "versions", "doc_chunks"}: raise ValueError(...)`) before interpolating them into SQL statements, even in private utility functions.
