## 2024-05-20 - SearXNG Startup Optimization
**Learning:** Instantiating `httpx.AsyncClient` inside a retry loop causes significant overhead due to repeated SSL context creation and connection pool setup. Reusing a single client instance outside the loop reduces health check execution time by up to ~90%.
**Action:** Always instantiate `httpx.AsyncClient` outside of retry loops to reuse connection pools and TLS contexts across attempts.
