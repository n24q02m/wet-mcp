
## 2025-03-09 - [Optimize httpx.AsyncClient initialization in retry loops]
**Learning:** Instantiating `httpx.AsyncClient` inside a retry loop causes severe overhead because each instantiation recreates connection pools, SSL contexts, and default headers. When benchmarking `async with httpx.AsyncClient() as client:`, calling it inside the loop took ~6x longer than instantiating it once outside the loop and making requests.
**Action:** Always wrap `httpx.AsyncClient()` around the retry loop `for` block, not inside it, when attempting multiple probes or retries, to reuse the connection layer and maximize throughput.
