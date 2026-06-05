## 2024-05-24 - Path Traversal in Token Storage
**Vulnerability:** The `token_store.py` module constructed file paths by directly concatenating user-controlled inputs (`provider`, `sub`) via `pathlib.Path` without validation. This allowed path traversal (e.g., using `../` or absolute paths) to read or write arbitrary files on the system with the application's permissions.
**Learning:** Even when using higher-level path abstractions like `pathlib`, string concatenation or `/` division with unvalidated user input is unsafe because the underlying OS resolution still respects traversal sequences.
**Prevention:** Always explicitly validate path components for dangerous characters (like `/`, `\`, and `..`) using an explicit string validation helper before passing them to file I/O operations or path constructors.

## 2025-02-27 - Remove Hardcoded Google Drive Client Secret
**Vulnerability:** A hardcoded Google Drive client secret was found in `src/wet_mcp/config.py` as a default fallback value for `google_drive_client_secret`.
**Learning:** Default parameter values in configuration objects (like Pydantic settings) must not contain sensitive credentials, even if they are intended for development or as examples, as they can be extracted and potentially abused.
**Prevention:** Always default sensitive fields to empty strings or `None` and enforce runtime checks to ensure they are explicitly provided via environment variables or secure configuration mechanisms.
