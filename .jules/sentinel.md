## 2024-05-24 - Path Traversal in Token Storage
**Vulnerability:** The `token_store.py` module constructed file paths by directly concatenating user-controlled inputs (`provider`, `sub`) via `pathlib.Path` without validation. This allowed path traversal (e.g., using `../` or absolute paths) to read or write arbitrary files on the system with the application's permissions.
**Learning:** Even when using higher-level path abstractions like `pathlib`, string concatenation or `/` division with unvalidated user input is unsafe because the underlying OS resolution still respects traversal sequences.
**Prevention:** Always explicitly validate path components for dangerous characters (like `/`, `\`, and `..`) using an explicit string validation helper before passing them to file I/O operations or path constructors.
## 2026-06-20 - Unsafe Dynamic SQL in SQLite PRAGMA calls
**Vulnerability:** Raw `PRAGMA table_info({table})` and `PRAGMA index_list({table})` using f-strings allows for SQL injection if the table identifier is unsanitized user input. SQLite DDL does not allow standard SQL bound parameters for table names.
**Learning:** SQLite introduced table-valued functions for introspection (`pragma_table_info(?)` and `pragma_index_list(?)`) which do support safe parameterization using bound variables.
**Prevention:** Always use parameterized `SELECT name FROM pragma_table_info(?)` or `SELECT name FROM pragma_index_list(?)` instead of using raw dynamic `PRAGMA` queries using string concatenation or f-strings. Note that when migrating from raw `PRAGMA` to `SELECT name FROM pragma_...`, the target column is returned at index 0 rather than index 1 (or by "name" dict lookup).

## 2026-07-06 - Prevent Path Hijacking in Subprocess

**Vulnerability:** `subprocess.run` was called with a partial executable path `["gh", ...]`, exposing a potential path hijacking vulnerability (CWE-426 / S607). An attacker could place a malicious executable named `gh` in a directory higher in the `PATH` hierarchy (or the working directory on Windows) to execute arbitrary code.
**Learning:** This existed because the command name was supplied as a literal string assuming the OS would correctly resolve it to the globally installed GitHub CLI, overlooking the risk of localized path hijacking, especially in cross-platform tooling.
**Prevention:** Always use `shutil.which("executable_name")` to resolve the absolute path to the binary before passing it to `subprocess.run()`, and gracefully handle cases where the executable is missing.
