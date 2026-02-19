# AGENTS.md - wet-mcp

Web Extract & Transform MCP Server. Python 3.13, uv, src layout.

## Build / Lint / Test Commands

```bash
uv sync --group dev                # Install dependencies
uv build                           # Build package (hatchling)
uv run ruff check .                # Lint
uv run ruff format --check .       # Format check
uv run ruff format .               # Format fix
uv run ruff check --fix .          # Lint fix
uv run ty check                    # Type check (Astral ty)
uv run pytest                      # Run all tests (integration excluded by default)
uv run pytest -m integration       # Run integration tests only

# Run a single test file
uv run pytest tests/test_config.py

# Run a single test function
uv run pytest tests/test_config.py::test_function_name -v

# Mise shortcuts
mise run setup     # Full dev environment setup
mise run lint      # ruff check + ruff format --check + ty check
mise run test      # pytest
mise run fix       # ruff check --fix --unsafe-fixes + ruff format
mise run dev       # uv run wet-mcp
```

### Pytest Configuration

- `asyncio_mode = "auto"` -- no `@pytest.mark.asyncio` needed
- Default timeout: 30 seconds per test
- Integration tests excluded by default (`-m 'not integration'`)
- Test files: `test_*.py` in `tests/` directory

## Code Style

### Formatting (Ruff)

- **Line length**: 88 (E501 ignored -- long lines allowed)
- **Quotes**: Double quotes
- **Indent**: 4 spaces (Python), 2 spaces (JSON/YAML/TOML)
- **Line endings**: LF
- **Target**: Python 3.13

### Ruff Rules

`select = ["E", "F", "W", "I", "UP", "B", "C4"]`, `ignore = ["E501"]`

- `I` = isort, `UP` = pyupgrade, `B` = bugbear, `C4` = comprehensions

### Type Checker (ty)

Lenient: `unresolved-import`, `unresolved-attribute`, `possibly-missing-attribute` all `"ignore"`.

### Import Ordering (isort via Ruff)

1. Standard library (`import asyncio`, `import json`, `import os`)
2. Third-party (`from loguru import logger`, `from mcp.server.fastmcp import FastMCP`)
3. Local (`from wet_mcp.config import settings`, `from wet_mcp.sources.crawler import ...`)

Lazy imports inside functions for heavy deps and to avoid circular deps.

```python
import asyncio
import json
import sys
from contextlib import asynccontextmanager

from loguru import logger
from mcp.server.fastmcp import Context, FastMCP

from wet_mcp.cache import WebCache
from wet_mcp.config import settings
```

### Type Hints

- Full type hints on all signatures: parameters and return types
- Modern syntax: `str | None`, `list[float]`, `dict[str, object]`
- `from __future__ import annotations` used in some files
- `py.typed` marker file present

### Naming Conventions

| Element            | Convention       | Example                            |
|--------------------|------------------|------------------------------------|
| Functions/methods  | snake_case       | `setup_api_keys`, `_warmup_searxng` |
| Private            | Leading `_`      | `_embed`, `_do_research`, `_web_cache` |
| Classes            | PascalCase       | `Settings`, `WebCache`, `DocsDB`   |
| Constants          | UPPER_SNAKE_CASE | `_EMBEDDING_CANDIDATES`, `_SEARXNG_TIMEOUT` |
| Modules            | snake_case       | `searxng_runner.py`, `security.py` |

### Error Handling

- MCP tools return error strings: `return "Error: query is required..."` (not exceptions)
- try/except with `logger.debug()` / `logger.warning()` for non-fatal failures
- Graceful fallback chains: Cloud -> Local, Tier 0 -> 1 -> 2 -> 3
- Custom `_with_timeout()` using `asyncio.wait` with grace period for cleanup
- `match action:` for tool action dispatch
- `asyncio.to_thread()` for wrapping sync operations

### File Organization

```
src/wet_mcp/
  __init__.py, __main__.py    # Package + entry
  config.py                   # Pydantic Settings (singleton)
  server.py                   # FastMCP server (largest, orchestrator)
  security.py                 # SSRF validation
  llm.py                      # LiteLLM integration
  cache.py                    # Web cache (SQLite)
  db.py                       # Docs DB (SQLite + sqlite-vec)
  embedder.py                 # Embedding backend (LiteLLM + local ONNX/GGUF)
  reranker.py                 # Reranker backend
  searxng_runner.py           # Embedded SearXNG subprocess
  setup.py                    # Auto-setup (SearXNG + Playwright)
  sync.py                     # rclone sync
  sources/                    # Data source integrations
    crawler.py, docs.py, searxng.py
  docs/                       # Tool documentation markdown
tests/                        # Test files mirror source modules
```

### Documentation

- Module-level docstrings on every file
- Google-style docstrings with `Args:`/`Returns:` sections
- Section separators: `# ---------------------------------------------------------------------------`
- `# noqa` comments used sparingly: `F401`, `E402`

### Commits

Conventional Commits: `type(scope): message`. Automated semantic release.

### Pre-commit Hooks

1. Ruff lint (`--fix --target-version=py313`) + format
2. ty type check
3. pytest (`--timeout=30 --tb=short -q`)
