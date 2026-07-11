1. **Identify Performance Optimization:** In `src/wet_mcp/sources/docs.py`, the `_NAV_RE`, `_FOOTER_RE`, and `_MKDOCS_UI_RE` regexes are evaluated per-line in `clean_markdown` (specifically inside the filtering loop lines 2210-2223). Since they all strictly check string prefixes or exact matches after stripping (as indicated by the `^\s*(?:...)` pattern structure), we can replace the regex matches with `str.startswith()` and exact string checks on the lowercased prefix (up to a fixed length, avoiding O(N) memory allocations for very long strings).
   - This aligns exactly with the memory entry: "Performance Optimization: When replacing anchored regexes with `.startswith()` or exact set matching, avoid calling `.lower()` on entire unbounded strings (like full Markdown paragraphs) as the O(N) string allocation introduces a performance regression on long lines. Instead, slice the string to the maximum expected prefix length before lowercasing (e.g., `stripped[:50].lower()`), or use pre-calculated exact-case string permutations."
2. **Implementation details:**
   - Define module-level tuples for `_NAV_PREFIXES` and `_FOOTER_PREFIXES` based on the content of the `_NAV_RE` and `_FOOTER_RE` patterns.
   - Define a set `_MKDOCS_UI_EXACT` for the `_MKDOCS_UI_RE` pattern.
   - In `clean_markdown` (line 2210+), extract the lowercased prefix `lower_prefix = stripped[:30].lower()`
   - Replace the `_NAV_RE.match`, `_FOOTER_RE.match`, and `_MKDOCS_UI_RE.match` calls with `.startswith()` and `in` checks on `lower_prefix`.
3. **Run Lint and Tests:** Run `uv run ruff check --fix . && uv run ruff format .` and `uv run pytest`.
4. **Complete pre-commit steps:** Complete pre-commit steps to ensure proper testing, verification, review, and reflection are done.
5. **Submit PR:** Submit the change with "⚡ Bolt: Replace regex matching with fast-path string checks in markdown cleaning"
