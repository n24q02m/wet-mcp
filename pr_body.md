🎯 **What:** The `_lifespan` function in `src/wet_mcp/server.py` was too long and complex, handling multiple distinct setup operations (API keys, web cache, docs db, searxng, etc.) inline. We refactored it by extracting these logical blocks into separate, focused helper functions: `_setup_api_keys`, `_setup_searxng`, `_setup_web_cache`, `_setup_docs_db`, and `_cleanup_resources`.

💡 **Why:** Breaking the function into smaller, well-named helpers drastically improves readability and maintainability. Each function now has a single, clear responsibility, making the codebase easier to understand, test, and modify without risking unintended side effects in unrelated initialization logic.

✅ **Verification:**
1. Ran format and lint checks (`uv run ruff format .` and `uv run ruff check . --fix`) to ensure the changes adhere to the project's strict styling rules.
2. Ran the full test suite (`uv run pytest`) which passed successfully, confirming that the functionality remained completely unchanged.
3. Manually reviewed `_lifespan` to verify the structure matches the intended abstraction.

✨ **Result:** A simplified `_lifespan` method that acts as a clean orchestrator for initialization and teardown tasks, leaving the implementation details to the newly created helper functions.
