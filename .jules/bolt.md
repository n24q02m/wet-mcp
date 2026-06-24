## 2025-05-14 - Consolidated Scoring Loop Optimization
**Learning:** Functions that perform multiple passes over the same content (e.g., using `re.finditer` multiple times or combining `splitlines()` loops) can be significantly optimized by consolidating logic into a single line-by-line loop. Using `str.startswith()` with a tuple is faster than anchored regex for prefix matching. Pre-filtering lines with substring checks before running expensive regex avoids unnecessary engine overhead for the majority of lines.
**Action:** Consolidate multiple string/line scans into a single `for ln in content.splitlines()` loop in performance-critical paths.
## 2025-05-14 - Parallelize Batch API Calls
**Learning:** Sequential batch API processing logic (e.g., in a `for` loop) can severely bottleneck processing of large inputs. `asyncio.gather` bounded by a semaphore effectively maximizes throughput without hitting rate limits.
**Action:** When making numerous API calls (such as chunks of a large text for embeddings), use an `asyncio.Semaphore` with `asyncio.gather` instead of awaiting sequential iterations in a loop.
## 2026-06-24 - Bounded Thread Pool Concurrency
**Learning:** When using `asyncio.to_thread` inside a batch operation (like iterating over dozens of pages to process markdown chunks), launching all tasks simultaneously via `asyncio.gather` can monopolize the default `ThreadPoolExecutor`. This starves other asyncio threads and degrades responsiveness.
**Action:** Use an `asyncio.Semaphore` to limit the number of concurrent thread pool submissions for CPU-bound tasks in batch operations.
