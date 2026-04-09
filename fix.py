with open('src/wet_mcp/setup_tool.py', 'r') as f:
    content = f.read()

import re

# In `_validate_cloud_models`, we can use a small async helper function or create a local event loop using `asyncio.run`
# But it fails because mock_backend is not returning a coroutine in some tests. Let's fix that by ensuring mock_backend.check_available is called in a way that handles coroutines properly.

# Let's change `asyncio.run(backend.check_available())` to an `if` statement to check if it's a coroutine.

content = content.replace(
"""            dims = await backend.check_available()
            if dims > 0:""",
"""            dims_or_coro = backend.check_available()
            import inspect
            if inspect.iscoroutine(dims_or_coro):
                import asyncio
                try:
                    dims = asyncio.get_running_loop().run_until_complete(dims_or_coro)
                except RuntimeError:
                    dims = asyncio.run(dims_or_coro)
            else:
                dims = dims_or_coro
            if dims > 0:"""
)

content = content.replace(
"""        try:
            reranker = init_reranker("cloud", rerank_model)
            if reranker.check_available():
                reranker_info = {"model": rerank_model}
        except Exception as exc:""",
"""        try:
            reranker = init_reranker("cloud", rerank_model)
            is_avail_or_coro = reranker.check_available()
            import inspect
            if inspect.iscoroutine(is_avail_or_coro):
                import asyncio
                try:
                    is_avail = asyncio.get_running_loop().run_until_complete(is_avail_or_coro)
                except RuntimeError:
                    is_avail = asyncio.run(is_avail_or_coro)
            else:
                is_avail = is_avail_or_coro
            if is_avail:
                reranker_info = {"model": rerank_model}
        except Exception as exc:"""
)

with open('src/wet_mcp/setup_tool.py', 'w') as f:
    f.write(content)
