## 2024-05-24 - Path Traversal in Token Storage
**Vulnerability:** The `token_store.py` module constructed file paths by directly concatenating user-controlled inputs (`provider`, `sub`) via `pathlib.Path` without validation. This allowed path traversal (e.g., using `../` or absolute paths) to read or write arbitrary files on the system with the application's permissions.
**Learning:** Even when using higher-level path abstractions like `pathlib`, string concatenation or `/` division with unvalidated user input is unsafe because the underlying OS resolution still respects traversal sequences.
**Prevention:** Always explicitly validate path components for dangerous characters (like `/`, `\`, and `..`) using an explicit string validation helper before passing them to file I/O operations or path constructors.

## 2024-06-16 - [Secure SQLite Introspection]
**Vulnerability:** Use of raw PRAGMA commands for SQLite database introspection (e.g., `PRAGMA table_info(table_name)`), which risks SQL injection if table names become dynamic.
**Learning:** SQLite provides parameterized table-valued functions (e.g., `pragma_table_info(?)`) that are a safer alternative to raw PRAGMA calls, allowing dynamic introspection without string concatenation risks.
**Prevention:** Always use parameterized table-valued PRAGMA functions (`SELECT name FROM pragma_table_info(?)`) instead of raw PRAGMAs.
