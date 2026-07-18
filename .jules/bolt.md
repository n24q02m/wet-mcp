## 2025-02-18 - Optimized String Window Scanning
**Learning:** Sliding windows using string slicing (`string[i : i+N]`) combined with `O(M * N)` substring matching operations within a loop traversing a full document causes exponential slowdowns on larger blocks of text.
**Action:** Always pre-calculate exact match indices via C-optimized `str.find()` first, then evaluate windows conditionally limited only to relevant indices/buckets rather than traversing blindly across the entire string length.
## 2024-03-24 - Avoid string joining for length checks in tight loops
**Learning:** In `_strip_nav_heading_blocks` (a hot path in markdown chunking), joining multiple string lines into a single string (`"\n".join(...)`) just to check if the combined length exceeds a small limit (50 chars) causes unnecessary memory allocation overhead and slows down processing.
**Action:** Replace `"\n".join` with an iterative loop that calculates the cumulative length (`content_length += len(line.strip())`), and exit early once the limit is reached.
## 2024-07-06 - Optimize string length checks in loops
**Learning:** Checking the length of accumulated string lists via `len("\n".join(lines))` inside a loop is O(N^2) time complexity and causes repeated memory allocations.
**Action:** Instead of joining strings purely to measure length, track length incrementally with an integer variable (e.g. `current_length += len(line) + (1 if lines else 0)`) to reduce time complexity to O(1) per iteration.

## 2024-07-06 - Fixing `ty` typchecker issues with `ty: ignore`
**Learning:** The typechecker used in this project is `ty`, not `mypy`. Ignore pragmas must take the form of `# ty: ignore[<rule>]`. For example, `type: ignore` and `ty: ignore` alone don't work, we need `# ty: ignore[unsupported-base]`. Additionally, we also have to clean up unused ignore pragmas or `ty check` fails with unused ignore comments.
**Action:** Always run `uv run ty check` as part of CI checks. Only add `# ty: ignore[<error>]` after verifying what the exact error name is, and remove obsolete `# ty: ignore` lines if they trigger `warning[unused-ignore-comment]`.

## 2023-11-20 - Fast String Suffix/Prefix matching with tuples
**Learning:** Python generator expressions inside `any()` for checking multiple prefixes/suffixes (e.g. `any(path.endswith(ext) for ext in EXTENSIONS)`) are slow due to Python-level iteration overhead.
**Action:** Always prefer passing a tuple of strings directly to `str.startswith()` and `str.endswith()` (e.g., `path.endswith(tuple(EXTENSIONS))`). This pushes the iteration down into optimized C code, yielding roughly ~5-7x speedup for prefix/suffix matching. Ensure the tuple is defined at the module level if used repeatedly.
## 2024-05-24 - Avoid micro-optimizing cold paths

**Learning:** Replacing idiomatic Python generator expressions (like `sum(1 for ...)`) with manual `for` loops in cold paths (like project locking logic) sacrifices code readability for negligible performance gains, and is considered a negative micro-optimization.
**Action:** When searching for performance improvements, verify that the targeted code is actually in a hot path or tight loop before applying optimizations that reduce readability.

## 2024-05-24 - Use short-circuiting in threshold checks

**Learning:** When checking for a threshold (e.g., detecting if a page is blocked by checking if `hits >= 2`), iterating over the full list of markers using `sum(1 for ...)` wastes cycles. An inline `for` loop with a `break` statement can short-circuit the evaluation as soon as the threshold is met.
**Action:** Apply early exits (`break` or `return`) when counting matches if a fixed threshold defines success or failure.

## 2024-05-27 - Use str.split() for multi-whitespace replacement
**Learning:** `re.sub(r"\s+", " ", text).strip()` is generally slower than `" ".join(text.split())` for collapsing multiple whitespace characters into single spaces, as the latter avoids regex engine overhead and is executed entirely in optimized C code.
**Action:** Use `" ".join(text.split())` instead of regex substitution when the goal is simply to replace continuous whitespace characters with a single space.
