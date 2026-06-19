## 2024-05-24 - Path Traversal in Token Storage
**Vulnerability:** The `token_store.py` module constructed file paths by directly concatenating user-controlled inputs (`provider`, `sub`) via `pathlib.Path` without validation. This allowed path traversal (e.g., using `../` or absolute paths) to read or write arbitrary files on the system with the application's permissions.
**Learning:** Even when using higher-level path abstractions like `pathlib`, string concatenation or `/` division with unvalidated user input is unsafe because the underlying OS resolution still respects traversal sequences.
**Prevention:** Always explicitly validate path components for dangerous characters (like `/`, `\`, and `..`) using an explicit string validation helper before passing them to file I/O operations or path constructors.
## 2026-06-19 - Parameterized SQL for PRAGMA Functions
**Vulnerability:** Found `f"PRAGMA table_info({table})"` which injects an unparameterized variable into the SQL statement. While `table` here is currently controlled by the application through migrations or tests, this pattern is a classic vector for SQL Injection. SQLite doesn't support parameterized input for raw PRAGMA statements.
**Learning:** SQLite has equivalent table-valued functions (e.g. `pragma_table_info(?)`) which *do* support parameter binding.
**Prevention:** Avoid dynamic SQL via f-strings where possible. Use parameterized equivalents like `SELECT name FROM pragma_table_info(?)` instead of `f"PRAGMA table_info({table})"`.
