## 2023-10-27 - Fast Whitespace Evaluation
**Learning:** Checking `if not ln or ln.isspace():` is more performant than `if ln.strip():` in hot loops because `str.strip()` forces memory allocation for a new string slice, even when simply validating whitespace.
**Action:** Avoid `str.strip()` as a boolean truthiness check in line-by-line parsing loops; use the allocation-free `.isspace()` check instead.

## 2023-10-27 - Prefix Matching Performance
**Learning:** Using `line.lstrip().startswith('...')` is significantly faster (~1.75x) than `_RE.match(line.strip())` because it avoids regex compilation, execution overhead, and allocates less memory compared to full `.strip()` when evaluating prefix patterns.
**Action:** Prefer `lstrip().startswith()` for simple prefix checks (e.g., matching markdown code fences or headers) over regex matches on stripped lines.
## 2023-11-20 - Redundant JSON parsing
**Learning:** Bypassing redundant `json.loads` followed by `json.dumps` in MCP tool handlers significantly reduces CPU overhead when the source functions already return pretty-printed JSON.
**Action:** Ensure that JSON parsing is only done when data modification is necessary. If a function returns an already correctly formatted JSON string, return it directly to the caller.
## 2023-10-27 - Optimize multiple string operations in conditionals
**Learning:** Calling `.strip()` multiple times per text line in complex conditions creates unnecessary string allocations. Combining generator expressions like `all(...)` with length checks can be redundant. If `len(set(text)) == 1` guarantees uniform characters, `all(c in SET for c in text)` can be safely replaced by an O(1) index check `text[0] in SET`.
**Action:** In text parsing loops, cache `.strip()` calls into local variables. Replace $O(N)$ string validations with $O(1)$ index accesses when a set length check guarantees uniform string content.
