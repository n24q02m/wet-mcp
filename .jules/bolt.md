## 2023-10-27 - Fast Whitespace Evaluation
**Learning:** Checking `if not ln or ln.isspace():` is more performant than `if ln.strip():` in hot loops because `str.strip()` forces memory allocation for a new string slice, even when simply validating whitespace.
**Action:** Avoid `str.strip()` as a boolean truthiness check in line-by-line parsing loops; use the allocation-free `.isspace()` check instead.

## 2023-10-27 - Prefix Matching Performance
**Learning:** Using `line.lstrip().startswith('...')` is significantly faster (~1.75x) than `_RE.match(line.strip())` because it avoids regex compilation, execution overhead, and allocates less memory compared to full `.strip()` when evaluating prefix patterns.
**Action:** Prefer `lstrip().startswith()` for simple prefix checks (e.g., matching markdown code fences or headers) over regex matches on stripped lines.
## 2023-11-20 - Redundant JSON parsing
**Learning:** Bypassing redundant `json.loads` followed by `json.dumps` in MCP tool handlers significantly reduces CPU overhead when the source functions already return pretty-printed JSON.
**Action:** Ensure that JSON parsing is only done when data modification is necessary. If a function returns an already correctly formatted JSON string, return it directly to the caller.

## 2023-11-20 - Regex vs string allocation (lstrip)
**Learning:** When attempting to optimize regexes with a "fast-path" character check in Python, calling `line.lstrip()` on every iteration allocates a new string in memory if there is leading whitespace. This allocation overhead often completely negates the performance benefit of bypassing the regex, making the code *slower* than just letting the C-optimized `re.match` run.
**Action:** Avoid unconditionally allocating strings (like `lstrip()`) in tight text-processing loops when trying to optimize regexes. A true fast path must avoid both regex execution *and* string allocation.
