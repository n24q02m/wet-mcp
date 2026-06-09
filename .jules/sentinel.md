## 2024-05-24 - Path Traversal in Token Storage
**Vulnerability:** The `token_store.py` module constructed file paths by directly concatenating user-controlled inputs (`provider`, `sub`) via `pathlib.Path` without validation. This allowed path traversal (e.g., using `../` or absolute paths) to read or write arbitrary files on the system with the application's permissions.
**Learning:** Even when using higher-level path abstractions like `pathlib`, string concatenation or `/` division with unvalidated user input is unsafe because the underlying OS resolution still respects traversal sequences.
**Prevention:** Always explicitly validate path components for dangerous characters (like `/`, `\`, and `..`) using an explicit string validation helper before passing them to file I/O operations or path constructors.

## 2024-05-25 - SQL Injection in SQLite PRAGMA Statements
**Vulnerability:** SQLite PRAGMA statements (like `PRAGMA table_info()` or `PRAGMA index_list()`) cannot accept bound parameters (`?`). Using f-strings to pass table names directly into `exec_driver_sql` or `execute` allows SQL injection if the table name is unvalidated. Even inside migration scripts, missing quoting leads to unintended behavior and potential injection.
**Learning:** SQLite identifiers and PRAGMA arguments must be manually quoted. Furthermore, any dynamic inputs that define table names should be validated against a strict allowlist.
**Prevention:**
1. Always enclose dynamic table names in single quotes within `PRAGMA` statements: `PRAGMA table_info('{table_name}')`.
2. When creating migration helpers that accept a table name dynamically, enforce an allowlist check before interpolating the string.
