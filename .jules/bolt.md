## 2024-05-14 - Optimize subprocess stderr reading
**Learning:** Sequential blocking `read()` on `subprocess.stderr` in a global asyncio event loop halts concurrent execution on the main thread, resulting in performance degradation when reading large outputs (e.g., from a crashed process).
**Action:** Use `await asyncio.to_thread(proc.stderr.read)` for I/O bound reading of large streams to avoid blocking the main thread event loop.
