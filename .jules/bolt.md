## 2023-10-27 - Fast Whitespace Evaluation
**Learning:** Checking `if not ln or ln.isspace():` is more performant than `if ln.strip():` in hot loops because `str.strip()` forces memory allocation for a new string slice, even when simply validating whitespace.
**Action:** Avoid `str.strip()` as a boolean truthiness check in line-by-line parsing loops; use the allocation-free `.isspace()` check instead.

## 2023-10-27 - Prefix Matching Performance
**Learning:** Using `line.lstrip().startswith('...')` is significantly faster (~1.75x) than `_RE.match(line.strip())` because it avoids regex compilation, execution overhead, and allocates less memory compared to full `.strip()` when evaluating prefix patterns.
**Action:** Prefer `lstrip().startswith()` for simple prefix checks (e.g., matching markdown code fences or headers) over regex matches on stripped lines.
## 2023-11-20 - Redundant JSON parsing
**Learning:** Bypassing redundant `json.loads` followed by `json.dumps` in MCP tool handlers significantly reduces CPU overhead when the source functions already return pretty-printed JSON.
**Action:** Ensure that JSON parsing is only done when data modification is necessary. If a function returns an already correctly formatted JSON string, return it directly to the caller.

## 2023-10-27 - str.split() redundant strip operations
**Learning:** `str.split()` without arguments automatically splits by arbitrary whitespace and discards empty strings. Using list comprehensions with `strip()` and truthiness checks (e.g., `[w.strip() for w in text.split() if w.strip()]`) creates unnecessary intermediate allocations.
**Action:** Use `text.split()` directly when arbitrary whitespace splitting is desired without empty elements.

## 2024-05-18 - String uniform validation
**Learning:** For uniform string validation (where `len(set(text)) == 1`), replacing an O(N) generator check like `all(c in ALLOWED for c in text)` with a simple O(1) index check `text[0] in ALLOWED` significantly improves iteration overhead.
**Action:** Always prefer array indexing to generator comprehensions when validating a uniformly matching string, and ensure that the stripped result is cached to avoid redundant allocations.
## 2024-10-30 - Sliding Window Optimizations
**Learning:** In string processing tasks like passage extraction that use a sliding window approach with multiple query terms, repeatedly checking for terms that don't even exist in the document wastes significant CPU cycles.
**Action:** When extracting passages, pre-filter query terms by first checking their existence in the overall text (`[term for term in query_terms if term in content]`). Additionally, record the `max_possible_score` so the algorithm can terminate early when the best possible window is found. This simple technique avoids redundant checking and provides an effective speedup.
## 2024-11-04 - Fast Path Substring Filtering for Regex Avoidance
**Learning:** Checking for substrings that are strict prerequisites for a regex match (e.g. `if "[" in ln or "http" in ln:`) before invoking a complex `.match()` or `.search()` provides a massive speedup on lines that do not match the target pattern, and is safe as long as the substring check is inclusive of all possible matching branches. Adding overly complex multi-condition substring filters using `and` logic can result in false negatives and actually slow down the execution if not carefully evaluated against the strict regex rules.
**Action:** When looping over large amounts of text line-by-line, implement `O(1)` substring `in` checks for critical characters or substrings that MUST exist in a valid regex match to prevent unneeded regex engine execution. Keep the fast path logic as simple as possible (e.g. single `or` condition).
