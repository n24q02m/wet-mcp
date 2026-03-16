## 2025-02-28 - Optimize SearXNG fallback with `asyncio.gather`
**What:** Replaced sequential `asyncio.wait_for` fetches in `do_docs_search` fallback with parallel `asyncio.gather`.
**Why:** Fallback mechanism sequentially fetched each fallback URL up to its timeout (`_FALLBACK_TIMEOUT`), resulting in compounded timeouts for a list of slow/unresponsive sources.
**Measurement:** Benchmarking 3 fallback URLs (1 slow/timeout, 1 error, 1 successful) showed execution time reduced from 3.00s to 1.50s (a 50% improvement).
