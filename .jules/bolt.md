## 2025-05-14 - Consolidated Scoring Loop Optimization
**Learning:** Functions that perform multiple passes over the same content (e.g., using `re.finditer` multiple times or combining `splitlines()` loops) can be significantly optimized by consolidating logic into a single line-by-line loop. Using `str.startswith()` with a tuple is faster than anchored regex for prefix matching. Pre-filtering lines with substring checks before running expensive regex avoids unnecessary engine overhead for the majority of lines.
**Action:** Consolidate multiple string/line scans into a single `for ln in content.splitlines()` loop in performance-critical paths.
## 2025-05-14 - Parallelize Batch API Calls
**Learning:** Sequential batch API processing logic (e.g., in a `for` loop) can severely bottleneck processing of large inputs. `asyncio.gather` bounded by a semaphore effectively maximizes throughput without hitting rate limits.
**Action:** When making numerous API calls (such as chunks of a large text for embeddings), use an `asyncio.Semaphore` with `asyncio.gather` instead of awaiting sequential iterations in a loop.
## 2024-06-22 - [Optimized document cleaning pipeline]
**Learning:** In `src/wet_mcp/sources/docs.py`, `_clean_doc_content` was doing repetitive `.splitlines()` and `\n.join()` operations inside helper functions, causing unnecessary string manipulations and memory allocation, especially for large documents.
**Action:** Consolidate list/string conversions by changing intermediate functions to accept `list[str]` instead of strings. Always try to process lists sequentially or string conversions once.
