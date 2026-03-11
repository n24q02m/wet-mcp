## 2026-03-08 - Atomic Cache Lookups
**Learning:** In SQLite >= 3.35.0, you can combine separate read-then-write operations into a single atomic query using the UPDATE ... RETURNING clause. This cuts database operations in half and eliminates race conditions.
**Action:** Look for read-modify-write patterns and consider using RETURNING to make them atomic.

## 2026-03-11 - Offload CPU-Bound Markdown Chunking to Thread Pool
**Learning:** Purely synchronous CPU-bound operations like markdown parsing and chunking (`chunk_markdown`), when running inside an `async` function loop, block the main asyncio thread. This prevents other concurrent tasks from progressing, leading to event loop starvation and high latency when processing many pages (e.g. hundreds of GitHub docs).
**Action:** Always wrap heavy CPU-bound synchronous calls with `await asyncio.to_thread(func, *args, **kwargs)` when called from an async context to maintain event loop responsiveness.
