## 2025-05-23 - BFS Queue Optimization
**Learning:** Python's `list.pop(0)` is O(n), which can become a bottleneck in queue-based algorithms like BFS crawlers. `collections.deque.popleft()` is O(1).
**Action:** Always use `collections.deque` for FIFO queues.
