## 2025-02-18 - FIFO Queue Optimization
**Learning:** The crawler used `list.pop(0)` for BFS queue, which is O(N) and degrades performance significantly as the queue grows (almost 100x slower for 50k items).
**Action:** Use `collections.deque` and `popleft()` for O(1) queue operations in BFS implementations.
