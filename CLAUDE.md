# wet-mcp

Python MCP Server: web search, content extraction, library docs, media analysis.
Xem `AGENTS.md` va `README.md` de hieu architecture va configuration.

## Cau truc

- `src/wet_mcp/` -- Package chinh (src layout)
  - `server.py` -- FastMCP server (orchestrator, file lon nhat)
  - `config.py` -- Pydantic Settings (singleton)
  - `cache.py`, `db.py`, `embedder.py`, `reranker.py` -- Infrastructure
  - `sources/` -- Data source integrations (crawler, docs, searxng)
- `tests/` -- Mirror source modules

## Lenh thuong dung

```bash
uv sync --group dev                # Cai dependencies
uv build                           # Build package (hatchling)
uv run ruff check .                # Lint
uv run ruff format --check .       # Kiem tra format
uv run ruff check --fix . && uv run ruff format .  # Fix
uv run ty check                    # Type check (ty lenient config)
uv run pytest                      # Test tat ca (integration excluded by default)
uv run pytest -m integration       # Chi integration tests
uv run pytest tests/test_config.py::test_function_name -v  # Test don le
uv run wet-mcp                     # Chay server

# Mise shortcuts
mise run setup     # Full dev env setup
mise run lint      # ruff check + ruff format --check + ty check
mise run test      # pytest
mise run fix       # ruff check --fix --unsafe-fixes + ruff format
mise run dev       # uv run wet-mcp
```

## Cau hinh quan trong

- **Python 3.13 bat buoc** -- 3.14+ KHONG tuong thich do SearXNG
- `requires-python = "==3.13.*"` trong pyproject.toml
- Ruff: line-length 88, target py313, rules E/F/W/I/UP/B/C4, ignore E501
- ty: lenient (unresolved-import, unresolved-attribute, possibly-missing-attribute all "ignore")

## Pytest

- `asyncio_mode = "auto"` -- KHONG can `@pytest.mark.asyncio`
- Default timeout: 30 seconds per test
- Integration tests excluded by default (`-m 'not integration'`)
- `addopts = "-m 'not integration'"` trong pyproject.toml

## Env vars

- KHONG co prefix ung dung (day la open-source MCP server)
- LLM: google-genai + openai (SDK) > disable if no key. Embed/Rerank: Cohere + Jina (cloud) > local ONNX
- Embedding: `EMBEDDING_BACKEND`, `EMBEDDING_MODEL`
- Reranking: `RERANK_BACKEND`, `RERANK_MODEL`
- SearXNG: `WET_AUTO_SEARXNG` (default true), `SEARXNG_URL` (external mode)
- Infisical: project `531b3027-70ca-4761-b149-9ec8fea80d4f`

## Release & Deploy

- Conventional Commits. Tag format: `v{version}`
- CD: workflow_dispatch, chon beta/stable
- Pipeline: PSR v10 -> PyPI (uv publish) -> Docker multi-arch (amd64 + arm64) -> DockerHub + GHCR -> MCP Registry
- Docker images: `n24q02m/wet-mcp`, `ghcr.io/n24q02m/wet-mcp`

## Pre-commit hooks

1. Ruff lint (`--fix --target-version=py313`) + format
2. ty type check
3. pytest (`--tb=short -q --timeout=30`)
4. Commit message: enforce `feat`/`fix` prefix

## Luu y quan trong

- Lazy imports ben trong functions cho heavy deps va tranh circular deps
- MCP tools return error strings (`return "Error: ..."`) -- KHONG raise exceptions
- Graceful fallback chains: Cloud -> Local, Tier 0 -> 1 -> 2 -> 3
- `match action:` cho tool action dispatch
- `asyncio.to_thread()` cho wrapping sync operations
- Embedding luu tai 768 dims (default). Doi provider KHONG lam hu vector table
- Renovate: Python upgrades DISABLED
