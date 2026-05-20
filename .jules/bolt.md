## 2024-05-24 - Avoid unconditional string allocations in text processing loops
**Learning:** In tight loops evaluating text line-by-line, creating intermediate lists with unconditional string allocations (e.g., `[line.strip() for line in lines]`) creates unnecessary CPU and memory overhead, especially when parsing large markdown files.
**Action:** Use a single-pass iteration and employ `if not line or line.isspace():` to skip empty lines efficiently before allocating stripped strings and evaluating patterns.
