## 2023-11-20 - Fast String Suffix/Prefix matching with tuples
**Learning:** Python generator expressions inside `any()` for checking multiple prefixes/suffixes (e.g. `any(path.endswith(ext) for ext in EXTENSIONS)`) are slow due to Python-level iteration overhead.
**Action:** Always prefer passing a tuple of strings directly to `str.startswith()` and `str.endswith()` (e.g., `path.endswith(tuple(EXTENSIONS))`). This pushes the iteration down into optimized C code, yielding roughly ~5-7x speedup for prefix/suffix matching. Ensure the tuple is defined at the module level if used repeatedly.
