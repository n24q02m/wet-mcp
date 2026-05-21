## 2023-10-27 - Fast Whitespace Evaluation
**Learning:** Checking `if not ln or ln.isspace():` is more performant than `if ln.strip():` in hot loops because `str.strip()` forces memory allocation for a new string slice, even when simply validating whitespace.
**Action:** Avoid `str.strip()` as a boolean truthiness check in line-by-line parsing loops; use the allocation-free `.isspace()` check instead.

## 2023-10-27 - Prefix Matching Performance
**Learning:** Using `line.lstrip().startswith('...')` is significantly faster (~1.75x) than `_RE.match(line.strip())` because it avoids regex compilation, execution overhead, and allocates less memory compared to full `.strip()` when evaluating prefix patterns.
**Action:** Prefer `lstrip().startswith()` for simple prefix checks (e.g., matching markdown code fences or headers) over regex matches on stripped lines.
## 2023-11-20 - Redundant JSON parsing
**Learning:** Bypassing redundant `json.loads` followed by `json.dumps` in MCP tool handlers significantly reduces CPU overhead when the source functions already return pretty-printed JSON.
**Action:** Ensure that JSON parsing is only done when data modification is necessary. If a function returns an already correctly formatted JSON string, return it directly to the caller.

## 2024-05-21 - Optimize redundant split comprehensions
**Learning:** `str.split()` without arguments already splits by arbitrary whitespace and discards empty strings natively. Iterating over the split output to apply `.strip()` and truthiness checks (e.g., `[w.strip() for w in query.split() if w.strip()]`) creates unnecessary memory allocations and CPU overhead, resulting in 2x slower execution than necessary.
**Action:** Replace redundant list comprehensions with `str.split()` natively when splitting text by whitespace where empty strings are already ignored.
