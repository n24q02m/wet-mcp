Dates below are the dates the change landed on `main`, taken from `git log`.
Each entry carries the commit holding it, so an entry can be located in the
repository history before the same change is proposed again.

## 2026-07-05 - Optimized String Window Scanning
**Commit:** 5d04261
**Learning:** Sliding windows using string slicing (`string[i : i+N]`) combined with `O(M * N)` substring matching operations within a loop traversing a full document causes exponential slowdowns on larger blocks of text.
**Action:** Always pre-calculate exact match indices via C-optimized `str.find()` first, then evaluate windows conditionally limited only to relevant indices/buckets rather than traversing blindly across the entire string length.

## 2026-07-10 - Avoid string joining for length checks in tight loops
**Commit:** 153b70c
**Learning:** In `_strip_nav_heading_blocks` (a hot path in markdown chunking), joining multiple string lines into a single string (`"\n".join(...)`) just to check if the combined length exceeds a small limit (50 chars) causes unnecessary memory allocation overhead and slows down processing.
**Action:** Replace `"\n".join` with an iterative loop that calculates the cumulative length (`content_length += len(line.strip())`), and exit early once the limit is reached.

## 2026-07-10 - Optimize string length checks in loops
**Commit:** 729bf0c
**Learning:** Checking the length of accumulated string lists via `len("\n".join(lines))` inside a loop is O(N^2) time complexity and causes repeated memory allocations.
**Action:** Instead of joining strings purely to measure length, track length incrementally with an integer variable (e.g. `current_length += len(line) + (1 if lines else 0)`) to reduce time complexity to O(1) per iteration.

## 2026-07-10 - Fixing `ty` typechecker issues with `ty: ignore`
**Commit:** 729bf0c
**Learning:** The typechecker used in this project is `ty`, not `mypy`. Ignore pragmas must take the form of `# ty: ignore[<rule>]`. For example, `type: ignore` and `ty: ignore` alone don't work, we need `# ty: ignore[unsupported-base]`. Additionally, we also have to clean up unused ignore pragmas or `ty check` fails with unused ignore comments.
**Action:** Always run `uv run ty check` as part of CI checks. Only add `# ty: ignore[<error>]` after verifying what the exact error name is, and remove obsolete `# ty: ignore` lines if they trigger `warning[unused-ignore-comment]`.

## 2026-07-11 - Fast String Suffix/Prefix matching with tuples
**Commit:** 23b5b55
**Learning:** Python generator expressions inside `any()` for checking multiple prefixes/suffixes (e.g. `any(path.endswith(ext) for ext in EXTENSIONS)`) are slow due to Python-level iteration overhead.
**Action:** Always prefer passing a tuple of strings directly to `str.startswith()` and `str.endswith()` (e.g., `path.endswith(tuple(EXTENSIONS))`). This pushes the iteration down into optimized C code, yielding roughly ~5-7x speedup for prefix/suffix matching. Ensure the tuple is defined at the module level if used repeatedly.

## 2026-07-17 - Avoid micro-optimizing cold paths
**Commit:** 1d9b8dd
**Learning:** Replacing idiomatic Python generator expressions (like `sum(1 for ...)`) with manual `for` loops in cold paths (like project locking logic) sacrifices code readability for negligible performance gains, and is considered a negative micro-optimization.
**Action:** When searching for performance improvements, verify that the targeted code is actually in a hot path or tight loop before applying optimizations that reduce readability.

## 2026-07-17 - Use short-circuiting in threshold checks
**Commit:** 1d9b8dd
**Learning:** When checking for a threshold (e.g., detecting if a page is blocked by checking if `hits >= 2`), iterating over the full list of markers using `sum(1 for ...)` wastes cycles. An inline `for` loop with a `break` statement can short-circuit the evaluation as soon as the threshold is met.
**Action:** Apply early exits (`break` or `return`) when counting matches if a fixed threshold defines success or failure.

## 2026-07-18 - Use str.split() for multi-whitespace replacement
**Commit:** 7cbab2e
**Learning:** `re.sub(r"\s+", " ", text).strip()` is generally slower than `" ".join(text.split())` for collapsing multiple whitespace characters into single spaces, as the latter avoids regex engine overhead and is executed entirely in optimized C code.
**Action:** Use `" ".join(text.split())` instead of regex substitution when the goal is simply to replace continuous whitespace characters with a single space.

## 2026-07-25 - Match host suffixes, not substrings
**Commit:** efdf601
**Learning:** `"rtfd.io" in netloc` is also true for `turbo.rtfd.io.evil.com`, whose first label then passes the `subdomain == lib_norm` comparison in `_score_discovery_result` and collects the ReadTheDocs relevance bonus for an attacker-controlled domain. CodeQL reports this shape as `py/incomplete-url-substring-sanitization` whenever the searched string contains a dot.
**Action:** Compare hosts against a module-level tuple of known hosts with `host == h or host.endswith(f".{h}")`, after lowercasing and stripping the port and any trailing dot. Keep every host the previous substring test accepted: dropping `readthedocs-hosted.com` would have silently lost the bonus for ReadTheDocs for Business projects.

## Rejected

Proposals that were reviewed and turned down, with the reason. They are recorded
here so the reason travels with the repository instead of staying behind in a
closed pull request.

### 2026-07-25 - Expanding a two-element `any()` into explicit `or` (#1556)
**Proposed:** rewrite `any(p in parsed_hp.netloc for p in ("readthedocs", "rtfd.io"))` and `any(p in all_urls for p in ("deprecate-holder", "placeholder"))` in `_score_discovery_result` as explicit `or` chains, claimed at "~3.5x faster".
**Why rejected:** the call site is not hot. `_score_discovery_result` runs once per registry result at `sources/docs.py:1826` — a handful of dicts per lookup — and only after `asyncio.gather` has queried the package registries over HTTP and `_pre_upgrade_discovery_results` has made its GitHub API calls. A saving on the order of 100 ns sits against hundreds of milliseconds of network work, and no measurement accompanied the claim. The 2026-07-17 entry above already covers this. The proposal also arrived under a title about `_DOC_DIRS`, which its diff never touched.
**Action:** Before proposing a membership-test rewrite, trace the call site to a loop that runs often enough for the saving to be observable, and quote a measurement taken on this repository. Where the surrounding work is I/O, prefer proposals that remove a request or a round-trip. The hostname half of that proposal was the part worth having, and it landed as efdf601.

### 2026-07-25 - Optimisation comments in source (#1556)
**Proposed:** annotate the rewritten conditions with a comment naming the optimisation and its expected impact.
**Why rejected:** this repository is public. A comment that names the tool which wrote it, and asserts an unmeasured speedup, is noise for every later reader of the file.
**Action:** Write comments that explain why the code is shaped the way it is, in the voice of the surrounding file — for example, the reason a fast path exists and the measurement that justified it. Leave authorship to the commit metadata.
