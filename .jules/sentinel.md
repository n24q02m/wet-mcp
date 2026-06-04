## 2024-05-24 - Path Traversal in Token Storage
**Vulnerability:** The `token_store.py` module constructed file paths by directly concatenating user-controlled inputs (`provider`, `sub`) via `pathlib.Path` without validation. This allowed path traversal (e.g., using `../` or absolute paths) to read or write arbitrary files on the system with the application's permissions.
**Learning:** Even when using higher-level path abstractions like `pathlib`, string concatenation or `/` division with unvalidated user input is unsafe because the underlying OS resolution still respects traversal sequences.
**Prevention:** Always explicitly validate path components for dangerous characters (like `/`, `\`, and `..`) using an explicit string validation helper before passing them to file I/O operations or path constructors.

## 2024-05-20 - Dynamic SQL Execution in DDL Migrations
**Vulnerability:** Dynamic SQL execution using f-strings for `ALTER TABLE ADD COLUMN` statements in database migration loops.
**Learning:** SQLite DDL statements (like `ALTER TABLE`) do not support parameter binding for identifiers. Using loops with f-strings to construct these statements is a security risk if the loop items are not strictly controlled or validated.
**Prevention:** Use hardcoded static SQL string literals for DDL statements instead of dynamic construction. If loops are necessary for conciseness, ensure the loop iterates over static strings rather than constructing them from variable parts.
