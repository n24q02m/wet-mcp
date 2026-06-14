## 2024-05-24 - Path Traversal in Token Storage
**Vulnerability:** The `token_store.py` module constructed file paths by directly concatenating user-controlled inputs (`provider`, `sub`) via `pathlib.Path` without validation. This allowed path traversal (e.g., using `../` or absolute paths) to read or write arbitrary files on the system with the application's permissions.
**Learning:** Even when using higher-level path abstractions like `pathlib`, string concatenation or `/` division with unvalidated user input is unsafe because the underlying OS resolution still respects traversal sequences.
**Prevention:** Always explicitly validate path components for dangerous characters (like `/`, `\`, and `..`) using an explicit string validation helper before passing them to file I/O operations or path constructors.

## 2024-05-24 - SQL Injection Risk in PRAGMA Queries
**Vulnerability:** SQLite `PRAGMA` commands like `PRAGMA table_info(table_name)` or `PRAGMA index_list(table_name)` do not support standard parameter binding (`?`), which often leads developers to use unsafe string formatting (e.g., f-strings) when the table name is variable. This introduces a risk of SQL injection if the table name originates from user input.
**Learning:** Modern SQLite provides table-valued functions for introspection that accept bound parameters, allowing safe, parameterized execution of what would otherwise be dynamic DDL-like commands. Note that the output format might differ slightly (e.g., column index shifts when projecting specific fields like `SELECT name FROM...`).
**Prevention:** Always use parameterized table-valued functions like `SELECT name FROM pragma_table_info(?)` or `SELECT name FROM pragma_index_list(?)` instead of string-formatted `PRAGMA` statements.
