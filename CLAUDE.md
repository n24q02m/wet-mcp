# wet-mcp

Python MCP Server: web search, content extraction, library docs, media analysis.
Xem `AGENTS.md` va `README.md` de hieu architecture va configuration.

## Cau truc

- `src/wet_mcp/` -- Package chinh (src layout)
  - `server.py` -- FastMCP server (orchestrator, file lon nhat)
  - `config.py` -- Pydantic Settings (singleton)
  - `cache.py`, `db.py`, `embedder.py`, `reranker.py` -- Infrastructure
  - `relay_setup.py` -- Zero-config relay: create session, poll for config
  - `relay_schema.py` -- Relay form schema (2 modes: local/cloud)
  - `sync.py` -- Google Drive sync (OAuth Device Code, httpx)
  - `token_store.py` -- Local token storage cho OAuth (~/.wet-mcp/tokens/)
  - `setup_tool.py` -- Warmup + setup-sync logic (MCP-callable)
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
- Integration/live/full tests excluded by default
- `addopts = "-m 'not integration and not live and not full'"` trong pyproject.toml

## Env vars

- KHONG co prefix ung dung (day la open-source MCP server)
- LLM: google-genai + openai (SDK) > disable if no key. Embed/Rerank: Jina > Gemini > OpenAI > Cohere (cloud) > local ONNX
- Embedding: `EMBEDDING_BACKEND`, `EMBEDDING_MODEL`
- Reranking: `RERANK_BACKEND`, `RERANK_MODEL`
- SearXNG: `WET_AUTO_SEARXNG` (default true), `SEARXNG_URL` (external mode)
- Sync: `SYNC_ENABLED` (default false), `GOOGLE_DRIVE_CLIENT_ID` (required for sync), `SYNC_FOLDER` (default "wet-mcp"), `SYNC_INTERVAL` (default 300s)
- Sync dung Google Drive API truc tiep (httpx). OAuth Device Code flow, token luu tai `~/.wet-mcp/tokens/google_drive.json`
- Relay: `MCP_RELAY_URL` (required for remote-relay mode, no default — wet-mcp default is local-relay per matrix)
- Secrets: skret SSM namespace `/wet-mcp/prod` (region `ap-southeast-1`)

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

## Known bugs / gotchas (phat hien 2026-04-18 E2E)

1. **Setup flow 2-phase race condition**:
   - Phase 1: user submit API keys form -> `writeConfig(SERVER_NAME, config)` -> `state=configured` (nhanh, ~5-30s)
   - Phase 2: Google Drive OAuth Device Code flow start (async, BLOCKING user hanh dong tren `google.com/device`)
   - Sau Phase 2, token save vao `~/.wet-mcp/tokens/google_drive.json`
   - **Gotcha:** E2E test script KHONG duoc kill server process sau Phase 1 -- PHAI wait cho `google_drive.json` ton tai TRUOC KHI exit. Neu kill som -> OAuth token mat -> next run phai re-auth.
   - Example fix: `phase-m-e2e-test/test_wet_full.py` phase_1 dung check `pathlib.Path(token_path).exists()` + 300s timeout after state=configured.

2. **GDrive token shared voi mnemo-mcp**:
   - Neu user auth mot account Google cho wet-mcp, mnemo-mcp co the auto-detect va skip device code flow (shared account pool ong)
   - Chua verify chinh xac mechanism, nhung observed 2026-04-18 E2E: setup mnemo ngay sau wet -> report "configured" rat nhanh
   - **Impact:** Tot cho UX, nhung can check xem logic share co security concern khong (token scope, privilege escalation)

3. **Relay "Setup complete" browser UI**: Python core-py relay implementation works correctly (browser hien "Setup complete!" sau phase 2). KHAC voi TS consumers (notion/email) bi stuck -- see `C:\Users\n24q02m-wlap\projects\mcp-core\CLAUDE.md` Known bugs #2.
