## 2025-02-18 - Optimized String Window Scanning
**Learning:** Sliding windows using string slicing (`string[i : i+N]`) combined with `O(M * N)` substring matching operations within a loop traversing a full document causes exponential slowdowns on larger blocks of text.
**Action:** Always pre-calculate exact match indices via C-optimized `str.find()` first, then evaluate windows conditionally limited only to relevant indices/buckets rather than traversing blindly across the entire string length.

## 2024-07-09 - Optimize length checks in string processing loops
**Learning:** In tight text processing loops (like `chunk_markdown`), checking the length of aggregated strings using `len("\n".join(lines))` introduces significant O(N) memory allocation and overhead, particularly for large documents where this check is performed on every heading.
**Action:** Always track the combined length incrementally with an integer variable (e.g., `current_length += len(line) + (1 if lines else 0)`) to achieve O(1) time complexity and eliminate unnecessary string joining operations in tight loops.
