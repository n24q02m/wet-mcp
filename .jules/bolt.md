## 2025-05-14 - Consolidated Scoring Loop Optimization
**Learning:** Functions that perform multiple passes over the same content (e.g., using `re.finditer` multiple times or combining `splitlines()` loops) can be significantly optimized by consolidating logic into a single line-by-line loop. Using `str.startswith()` with a tuple is faster than anchored regex for prefix matching. Pre-filtering lines with substring checks before running expensive regex avoids unnecessary engine overhead for the majority of lines.
**Action:** Consolidate multiple string/line scans into a single `for ln in content.splitlines()` loop in performance-critical paths.
## 2025-05-14 - Parallelize Batch API Calls
**Learning:** Sequential batch API processing logic (e.g., in a `for` loop) can severely bottleneck processing of large inputs. `asyncio.gather` bounded by a semaphore effectively maximizes throughput without hitting rate limits.
**Action:** When making numerous API calls (such as chunks of a large text for embeddings), use an `asyncio.Semaphore` with `asyncio.gather` instead of awaiting sequential iterations in a loop.
## 2025-05-14 - Bound Concurrency for CPU-Bound Async Tasks
**Learning:** Using `asyncio.to_thread` for CPU-bound tasks inside concurrent loops like `asyncio.gather` can spawn too many threads, leading to thread pool exhaustion and event loop starvation.
**Action:** Always bound concurrency using an `asyncio.Semaphore` (e.g., `asyncio.Semaphore(10)`) when fanning out tasks that internally delegate to `asyncio.to_thread`.
