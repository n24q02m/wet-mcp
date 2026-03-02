## 2023-10-27 - [Fix URL-encoded path traversal in media download]
**Vulnerability:** URL-encoded characters in filenames could bypass `.split("/")` checks. While `filepath.resolve().is_relative_to(output_path)` caught standard `../`, Windows-specific slashes (`..\`) or URL-encoded paths could potentially lead to bypassing sanitization and incorrectly extracting the file name.
**Learning:** Naive `.split("/")` is insufficient for parsing URLs correctly, especially given the presence of query strings (`?`) and URL-encoded elements (`%2f`).
**Prevention:** Always use robust path extraction functions such as `urllib.parse.urlparse`, `urllib.parse.unquote`, and `pathlib.Path().name` instead of string manipulations.
