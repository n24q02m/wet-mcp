1. **Analyze `_fetch_and_chunk_docs` in `src/wet_mcp/server.py`**:
   The function `_fetch_and_chunk_docs` calls `asyncio.to_thread(chunk_markdown, ...)` inside loops for parsing GitHub markdown chunks (`gh_chunks`) and crawled pages (`chunks`). Currently it looks like:
   ```python
        for page in gh_pages:
            page_chunks = await asyncio.to_thread(
                chunk_markdown,
                content=page["content"],
                url=page.get("url", ""),
            )
            # ...
   ```
   and
   ```python
    for page in pages:
        page_chunks = await asyncio.to_thread(
            chunk_markdown,
            content=page["content"],
            url=page.get("url", ""),
        )
        # ...
   ```
   This means that `asyncio.to_thread` is awaited sequentially, blocking the event loop on thread completion for each page one by one. This is an async anti-pattern and can be significantly optimized by running these blocking thread operations concurrently using `asyncio.gather`.

2. **Refactor the Loops using `asyncio.gather`**:
   - Create a local asynchronous helper function `_process_page` (or similar) that wraps the `asyncio.to_thread` call and the subsequent chunk title updating logic.
   - For `gh_pages`: Use `asyncio.gather` to concurrently process all `gh_pages` and then collect `gh_chunks`.
   - For `pages`: Use `asyncio.gather` to concurrently process all `pages` and then collect `chunks`.

3. **Performance Impact**:
   - The sequential execution time is $O(\sum_{i=1}^N T_{chunk}(page_i))$, whereas concurrent execution reduces it to $O(\max_i T_{chunk}(page_i))$ plus slight overhead, assuming sufficient thread pool workers. This reduces the total latency of document chunking, a CPU-bound operation, especially when fetching numerous documentation pages simultaneously.

4. **Add Bolt Journal Entry**:
   - I will document this codebase-specific anti-pattern of "sequential `asyncio.to_thread` calls in loops for CPU-bound tasks" in `.jules/bolt.md`.

5. **Run Pre-Commit Checks & Submit**:
   - Execute formatting/linting using `uv run ruff check .` and `uv run ruff format .`
   - Run tests to ensure no regressions using `uv run pytest`.
   - Use `pre_commit_instructions` tool and finish by calling `submit` with the prefix "⚡ Bolt: [performance improvement]".
