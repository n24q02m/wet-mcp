## 2023-10-27 - Fast Whitespace Evaluation
**Learning:** Checking `if not ln or ln.isspace():` is more performant than `if ln.strip():` in hot loops because `str.strip()` forces memory allocation for a new string slice, even when simply validating whitespace.
**Action:** Avoid `str.strip()` as a boolean truthiness check in line-by-line parsing loops; use the allocation-free `.isspace()` check instead.

## 2023-10-27 - Prefix Matching Performance
**Learning:** Using `line.lstrip().startswith('...')` is significantly faster (~1.75x) than `_RE.match(line.strip())` because it avoids regex compilation, execution overhead, and allocates less memory compared to full `.strip()` when evaluating prefix patterns.
**Action:** Prefer `lstrip().startswith()` for simple prefix checks (e.g., matching markdown code fences or headers) over regex matches on stripped lines.
## 2023-11-20 - Redundant JSON parsing
**Learning:** Bypassing redundant `json.loads` followed by `json.dumps` in MCP tool handlers significantly reduces CPU overhead when the source functions already return pretty-printed JSON.
**Action:** Ensure that JSON parsing is only done when data modification is necessary. If a function returns an already correctly formatted JSON string, return it directly to the caller.
## 2026-05-17 - splitlines() and strip() overhead
**Learning:** In `src/wet_mcp/sources/docs.py`, iterating with `content.splitlines()` combined with `line.strip()` introduces unnecessary overhead due to creating many string copies. However, when regexes with end-of-line anchors (`$`) are used on lines, replacing `splitlines()` with `split('\n')` is unsafe on Windows because `split('\n')` leaves `\r` attached, breaking the regex.
**Action:** To safely optimize such hot loops without regressions, keep `content.splitlines()` but replace list comprehensions and multiple `sum()` generator iterations with a single `for` loop, and avoid fully `strip()`-ing lines when `isspace()` suffices for emptiness checks.
