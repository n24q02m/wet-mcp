## 2023-10-27 - Fast Whitespace Evaluation
**Learning:** Checking `if not ln or ln.isspace():` is more performant than `if ln.strip():` in hot loops because `str.strip()` forces memory allocation for a new string slice, even when simply validating whitespace.
**Action:** Avoid `str.strip()` as a boolean truthiness check in line-by-line parsing loops; use the allocation-free `.isspace()` check instead.
## 2024-03-06 - Avoid .strip() and compiled regex in tight string processing loops
**Learning:** In tight loops evaluating text line-by-line (e.g., markdown chunking in `src/wet_mcp/sources/docs.py`), using `line.strip() == ""` creates unnecessary string object allocations. Furthermore, `regex.match(line.strip())` to check for specific prefixes adds compilation/matching overhead.
**Action:** Prefer `(not line or line.isspace())` over `line.strip() == ""` to check for empty or whitespace-only lines. For prefix matching, prefer `line.lstrip().startswith("...")` over regex `match` on a stripped string to avoid unnecessary list allocation and regex overhead, which yields measurable performance gains.
