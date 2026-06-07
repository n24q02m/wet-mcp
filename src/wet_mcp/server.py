"""WET MCP Server - Main server definition."""

import asyncio
import functools
import io
import json
import os
import sys

# Fix Windows console encoding for Unicode output
if sys.platform == "win32":
    for _s in (sys.stdin, sys.stdout, sys.stderr):
        if isinstance(_s, io.TextIOWrapper):
            _s.reconfigure(encoding="utf-8", errors="replace")

from contextlib import asynccontextmanager
from importlib.resources import files
from pathlib import Path
from urllib.parse import urlparse

from loguru import logger
from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from wet_mcp.cache import WebCache
from wet_mcp.config import _EMBEDDING_CANDIDATES, settings
from wet_mcp.db import DocsDB
from wet_mcp.searxng_runner import ensure_searxng, stop_searxng
from wet_mcp.security import wrap_external_content
from wet_mcp.sources.crawler import (
    crawl as _crawl,
)
from wet_mcp.sources.crawler import (
    extract as _extract,
)
from wet_mcp.sources.crawler import (
    list_media,
    shutdown_crawler,
)
from wet_mcp.sources.crawler import (
    sitemap as _sitemap,
)
from wet_mcp.sources.searxng import search as searxng_search
from wet_mcp.transport_check import is_uvx_tool_venv, uvx_searxng_blocked_error

# Configure logging
logger.remove()
logger.add(sys.stderr, level=settings.log_level)

# Fixed embedding dimensions for sqlite-vec.
# All embeddings are truncated to this size so switching models never
# breaks the vector table. Override via EMBEDDING_DIMS env var.
_DEFAULT_EMBEDDING_DIMS = 768

# Reranking: retrieve more candidates than final limit, then rerank.
_RERANK_CANDIDATE_MULTIPLIER = 3

# Module-level state (set during lifespan)
_web_cache: WebCache | None = None
_docs_db: DocsDB | None = None
_embedding_dims: int = 0


def _require_credentials() -> str | None:
    """Check if credentials are configured. Returns error JSON if not, None if OK.

    Branching:

    * **HTTP multi-user request** (``_current_sub`` set via auth_scope) —
      look up the per-sub PerPluginStore bucket. If empty, return
      AWAITING_SETUP error so the user opens the relay form. If non-empty,
      apply to ``os.environ`` for the duration of the asyncio task so the
      existing provider-init code (settings.setup_providers, JINA/Gemini
      client builders, …) picks the right user's keys, and allow the call.
      Per-asyncio-task contextvar isolation guarantees concurrent users
      see only their own values.

    * **Stdio / single-user HTTP / no JWT** — ``_current_sub`` is ``None``;
      fall back to the legacy ``CredentialState`` machine driven by env
      vars at startup (resolve_credential_state path). State machine:
      AWAITING_SETUP -> blocked, LOCAL -> allow, CONFIGURED -> allow.
    """
    from wet_mcp.credential_state import (
        CredentialState,
        credentials_for_current_request,
        get_current_sub,
        get_setup_url,
        get_state,
    )

    sub = get_current_sub()
    if sub is not None:
        creds = credentials_for_current_request()
        if not creds:
            return json.dumps(
                {
                    "error": "Credentials not configured",
                    "state": "awaiting_setup",
                    "sub": sub,
                    "instructions": (
                        "Open the wet-mcp relay form (see the OAuth setup "
                        "URL in your client) and submit at least one of "
                        "JINA_AI_API_KEY / GEMINI_API_KEY / OPENAI_API_KEY "
                        "/ COHERE_API_KEY for this user."
                    ),
                }
            )
        # Apply per-sub creds to env for the request. Python contextvar +
        # asyncio task isolation ensures concurrent requests for different
        # subs do not race on os.environ at the per-call boundary used by
        # downstream provider builders. (We never reset because each
        # request overwrites with its own sub's values; missing keys for
        # this sub fall through to whatever the previous request set,
        # which is acceptable per spec §4.2 since `_require_credentials`
        # already verified at least one key is present.)
        for key, value in creds.items():
            if value:
                os.environ[key] = value
        return None

    state = get_state()
    if state == CredentialState.AWAITING_SETUP:
        url = get_setup_url()
        return json.dumps(
            {
                "error": "Credentials not configured",
                "state": "awaiting_setup",
                "setup_url": url,
                "instructions": (
                    "API keys required. Set one of "
                    "JINA_AI_API_KEY / GEMINI_API_KEY / OPENAI_API_KEY / "
                    "COHERE_API_KEY in the environment, or run wet-mcp in "
                    "HTTP mode (--http / MCP_TRANSPORT=http) to configure "
                    "via browser, or call config(action='setup_skip') to "
                    "opt into local-only mode."
                ),
            }
        )
    return None


async def _warmup_searxng() -> None:
    """Run heavy setup and pre-warm SearXNG in background.

    Non-fatal: if startup fails, the first search call will retry.
    """
    try:
        from wet_mcp.setup import run_auto_setup

        await asyncio.to_thread(run_auto_setup)

        # Pre-import crawl4ai
        await asyncio.to_thread(__import__, "crawl4ai")
        logger.info("Crawl4AI background load complete")

        from wet_mcp.searxng_runner import ensure_searxng

        url = await ensure_searxng()
        logger.info(f"SearXNG pre-warmed at {url}")
    except Exception as e:
        logger.debug(f"SearXNG pre-warm failed (non-fatal): {e}")


def _detect_gh_token() -> str | None:
    """Try to get GitHub token from gh CLI (GitHub CLI).

    Runs 'gh auth token' and returns the token string if available.
    Returns None if gh CLI is not installed or not authenticated.
    """
    import shutil
    import subprocess

    if not shutil.which("gh"):
        return None

    try:
        result = subprocess.run(
            ["gh", "auth", "token"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            token = result.stdout.strip()
            if token:
                return token
    except Exception:
        pass
    return None


@asynccontextmanager
async def _lifespan(_server: FastMCP):
    """Server lifespan: startup SearXNG, init cache/docs DB, cleanup on shutdown."""
    warmup_task = await _lifespan_startup()
    yield
    await _lifespan_shutdown(warmup_task)


async def _lifespan_startup() -> asyncio.Task | None:
    """Initialize all server components. Returns SearXNG warmup task."""
    global _web_cache, _docs_db, _embedding_dims

    logger.info("Starting WET MCP Server...")

    # Non-blocking credential resolution (fast, <10ms)
    from wet_mcp.credential_state import (
        CredentialState,
        get_state,
        resolve_credential_state,
        set_state,
    )

    resolve_credential_state()

    # Stdio mode has no in-process credential form, so AWAITING_SETUP would
    # block every tool call forever. Promote it to LOCAL so basic SearXNG
    # search + local ONNX embed/rerank work with zero env. Tools that
    # require specific upstream API creds (e.g. GDrive sync) still return
    # a helpful runtime error if their env var is missing.
    is_stdio = (
        "--stdio" in sys.argv or os.environ.get("MCP_TRANSPORT") in (None, "", "stdio")
    ) and not (
        "--http" in sys.argv
        or os.environ.get("MCP_TRANSPORT") == "http"
        or os.environ.get("TRANSPORT_MODE") == "http"
    )
    if is_stdio and get_state() == CredentialState.AWAITING_SETUP:
        logger.info(
            "Stdio mode with no creds; running in LOCAL mode "
            "(SearXNG + local ONNX embed/rerank, no cloud keys required)."
        )
        set_state(CredentialState.LOCAL)

    # 1. Setup provider mode (sdk or local)
    from wet_mcp.config import settings

    mode = settings.setup_providers()

    # Warn about GitHub token for library docs discovery
    if not (os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")):
        # Try to get token from gh CLI (GitHub CLI)
        gh_token = _detect_gh_token()
        if gh_token:
            os.environ["GITHUB_TOKEN"] = gh_token
            logger.info("GITHUB_TOKEN loaded from gh CLI (gh auth token)")
        else:
            logger.warning(
                "No GITHUB_TOKEN set. Library docs discovery will use unauthenticated "
                "GitHub API (60 req/hr limit). Set GITHUB_TOKEN or run 'gh auth login'."
            )

    # SearXNG is pre-warmed eagerly as a background task to eliminate
    # startup latency on the first search call. If this instance finds an
    # existing healthy SearXNG (started by another MCP server instance), it
    # reuses it instead of spawning a new subprocess.
    #
    # Stdio uvx mode skips warmup entirely: the search/research/docs/similar
    # actions are gated by `is_uvx_tool_venv()` and return a clear error
    # pointing to Docker mode. Warming SearXNG in uvx mode wastes a Docker
    # spawn the user will never get value from.
    warmup_task: asyncio.Task | None = None
    if settings.wet_auto_searxng and not is_uvx_tool_venv():
        warmup_task = asyncio.create_task(_warmup_searxng())

    # 2. Initialize web cache
    if settings.wet_cache:
        cache_path = settings.get_cache_db_path()
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        _web_cache = WebCache(cache_path)
        logger.info("Web cache enabled")

    # 3. Initialize embedding backend (dual-backend: cloud or local)
    _embedding_dims = settings.resolve_embedding_dims()
    if _embedding_dims == 0:
        _embedding_dims = _DEFAULT_EMBEDDING_DIMS

    async def _init_backends_task():
        try:
            await _init_embedding_backend(mode)
            await _init_reranker_backend(mode)
        except Exception as e:
            logger.error(f"Background backend init failed: {e}")

    asyncio.create_task(_init_backends_task())

    # 5. Initialize docs DB + run Alembic migrations (auto-migrate-on-startup
    #    with backup-before-migrate per spec §8). DocsDB._create_tables is
    #    still the bootstrap path for fresh DBs (CREATE TABLE IF NOT EXISTS);
    #    Alembic stamps the baseline + applies any forward migrations.
    docs_path = settings.get_db_path()
    docs_path.parent.mkdir(parents=True, exist_ok=True)
    _docs_db = DocsDB(docs_path, embedding_dims=_embedding_dims)
    try:
        from wet_mcp.migrations import run_migrations_on_startup

        run_migrations_on_startup(docs_path)
    except Exception as e:  # pragma: no cover - never block startup
        logger.warning(f"Migrations skipped: {e}")

    # 5b. Tier 1 metadata warmup (Phase 2). Lazy chunk ingestion is
    # triggered on first docs_query for an unseeded library.
    try:
        from wet_mcp.sources.tier1_warmup import maybe_warm

        await asyncio.to_thread(maybe_warm, _docs_db)
    except Exception as e:  # pragma: no cover - never block startup
        logger.warning(f"Tier 1 warmup skipped: {e}")

    # Start auto-sync via the active backend (XOR semantics):
    # * SYNC_S3_BUCKET set -> S3 mode (operator deploy, Method 2/3 Docker).
    #   The GDrive OAuth flow is skipped entirely.
    # * No S3 bucket -> GDrive mode (Method 1 uvx, per-user Device Code).
    from wet_mcp.sync import resolve_active_backend

    active_backend = resolve_active_backend()
    if active_backend == "s3":
        logger.info(
            f"Sync backend: s3 (bucket={settings.sync_s3_bucket}, "
            f"prefix={settings.sync_s3_prefix})"
        )
        from wet_mcp.sync import start_s3_auto_sync

        start_s3_auto_sync(_docs_db)
    elif settings.google_drive_client_id:
        logger.info("Sync backend: gdrive (Device Code OAuth via relay)")
        from wet_mcp.sync import start_auto_sync

        start_auto_sync(_docs_db)

    return warmup_task


async def _lifespan_shutdown(warmup_task: asyncio.Task | None) -> None:
    """Shut down all server components."""
    global _web_cache, _docs_db

    logger.info("Shutting down WET MCP Server...")

    # Cancel SearXNG warmup task if still running
    if warmup_task and not warmup_task.done():
        warmup_task.cancel()
        try:
            await warmup_task
        except (asyncio.CancelledError, Exception):
            pass

    # Stop auto-sync (whichever backend is active)
    from wet_mcp.config import settings
    from wet_mcp.sync import resolve_active_backend

    active_backend = resolve_active_backend()
    if active_backend == "s3":
        from wet_mcp.sync import stop_s3_auto_sync

        stop_s3_auto_sync()
    elif settings.google_drive_client_id:
        from wet_mcp.sync import stop_auto_sync

        stop_auto_sync()

    # Close databases
    if _docs_db:
        _docs_db.close()
        _docs_db = None
    if _web_cache:
        _web_cache.close()
        _web_cache = None

    # Shut down the shared browser pool first (may take a few seconds)
    try:
        await shutdown_crawler()
    except Exception as exc:
        logger.debug(f"Browser pool shutdown error (non-fatal): {exc}")

    stop_searxng()


async def _init_embedding_backend(mode: str) -> None:
    """Initialize the embedding backend based on credential state and config.

    - AWAITING_SETUP: skip init entirely (tools are blocked anyway)
    - CONFIGURED: cloud only — no silent local fallback
    - LOCAL (explicit skip): local only
    """
    global _embedding_dims
    from wet_mcp.credential_state import CredentialState, get_state
    from wet_mcp.embedder import init_backend

    cred_state = get_state()

    if cred_state == CredentialState.AWAITING_SETUP:
        logger.info("Embedding: skipped (credentials not configured)")
        return

    backend_type = settings.resolve_embedding_backend()

    if cred_state == CredentialState.LOCAL or backend_type == "local":
        local_model = settings.resolve_local_embedding_model()
        try:
            backend = await asyncio.to_thread(init_backend, "local", local_model)
            native_dims = await backend.check_available()
            if native_dims > 0:
                if _embedding_dims == 0:
                    _embedding_dims = _DEFAULT_EMBEDDING_DIMS
                logger.info(
                    f"Embedding: local {local_model} "
                    f"(native={native_dims}, stored={_embedding_dims})"
                )
            else:
                logger.error("Local embedding model not available")
        except Exception as e:
            logger.error(f"Local embedding init failed: {e}")
        return

    # CONFIGURED + cloud backend
    model = settings.resolve_embedding_model()
    if model:
        try:
            backend = await asyncio.to_thread(init_backend, "cloud", model)
            native_dims = await backend.check_available()
            if native_dims > 0:
                if _embedding_dims == 0:
                    _embedding_dims = _DEFAULT_EMBEDDING_DIMS
                logger.info(
                    f"Embedding: {model} "
                    f"(native={native_dims}, stored={_embedding_dims})"
                )
                return
        except Exception as e:
            logger.warning(f"Embedding model {model} not available: {e}")
    elif mode == "sdk":
        for candidate in _EMBEDDING_CANDIDATES:
            try:
                backend = await asyncio.to_thread(init_backend, "cloud", candidate)
                native_dims = await backend.check_available()
                if native_dims > 0:
                    if _embedding_dims == 0:
                        _embedding_dims = _DEFAULT_EMBEDDING_DIMS
                    logger.info(
                        f"Embedding: {candidate} "
                        f"(native={native_dims}, stored={_embedding_dims})"
                    )
                    return
            except Exception:
                continue

    logger.error("Cloud embedding not available and local fallback is disabled")


async def _init_reranker_backend(mode: str) -> None:
    """Initialize the reranker backend based on credential state and config.

    - AWAITING_SETUP: skip init entirely (tools are blocked anyway)
    - CONFIGURED: cloud only — no silent local fallback
    - LOCAL (explicit skip): local only
    """
    from wet_mcp.credential_state import CredentialState, get_state

    cred_state = get_state()

    if cred_state == CredentialState.AWAITING_SETUP:
        logger.info("Reranker: skipped (credentials not configured)")
        return

    rerank_backend_type = settings.resolve_rerank_backend()

    if not rerank_backend_type:
        logger.info("Reranking disabled")
        return

    from wet_mcp.reranker import init_reranker

    if cred_state == CredentialState.LOCAL or rerank_backend_type == "local":
        local_model = settings.resolve_local_rerank_model()
        try:
            reranker = await asyncio.to_thread(init_reranker, "local", local_model)
            available = await asyncio.to_thread(reranker.check_available)
            if available:
                logger.info(f"Reranker: local {local_model}")
            else:
                logger.error("Local reranker not available")
        except Exception as e:
            logger.error(f"Local reranker init failed: {e}")
        return

    # CONFIGURED + cloud backend
    model = settings.resolve_rerank_model()
    if model:
        try:
            reranker = await asyncio.to_thread(init_reranker, "cloud", model)
            available = await asyncio.to_thread(reranker.check_available)
            if available:
                logger.info(f"Reranker: {model} (cloud)")
                return
        except Exception as e:
            logger.warning(f"Cloud reranker {model} not available: {e}")

    logger.error("Cloud reranker not available and local fallback is disabled")


# --- Helpers ---


async def _embed(text: str, is_query: bool = False) -> list[float] | None:
    """Embed text if backend is available.

    Args:
        text: Text to embed.
        is_query: If True, use query_embed for instruction-aware asymmetric
            retrieval (Qwen3). Document embeddings stay raw.
    """
    from wet_mcp.embedder import Qwen3EmbedBackend, get_backend

    backend = get_backend()
    if not backend:
        return None
    try:
        if is_query and isinstance(backend, Qwen3EmbedBackend):
            return await backend.embed_single_query(text, _embedding_dims)
        return await backend.embed_single(text, _embedding_dims)
    except Exception as e:
        logger.debug(f"Embedding failed: {e}")
        return None


async def _embed_batch(texts: list[str]) -> list[list[float]] | None:
    """Embed batch of texts if backend is available."""
    from wet_mcp.embedder import get_backend

    backend = get_backend()
    if not backend:
        return None
    try:
        return await backend.embed_texts(texts, _embedding_dims)
    except Exception as e:
        logger.debug(f"Batch embedding failed: {e}")
        return None


async def _rerank_results(
    query: str,
    results: list[dict],
    top_n: int,
) -> list[dict]:
    """Rerank search results if reranker is available.

    Falls back to original results if reranking fails or is unavailable.
    """
    from wet_mcp.reranker import get_reranker

    reranker = get_reranker()
    if not reranker or len(results) <= top_n:
        return results[:top_n]

    try:
        documents = [r["content"] for r in results]
        ranked = await asyncio.to_thread(reranker.rerank, query, documents, top_n)
        if ranked:
            reranked = []
            for idx, score in ranked:
                if idx < len(results):
                    result = results[idx].copy()
                    result["score"] = round(score, 4)
                    reranked.append(result)
            return reranked
    except Exception as e:
        logger.debug(f"Reranking failed, using original order: {e}")

    return results[:top_n]


# Initialize MCP server
mcp = FastMCP(
    name="wet",
    instructions=(
        "Web Extended Toolkit MCP Server. "
        "IMPORTANT: `search` and `extract` serve different purposes. "
        "`search` FINDS information (returns result listings with titles, URLs, snippets). "
        "`extract` READS content from a specific URL (returns full page text). "
        "Typical workflow: search first to find URLs, then extract to read them. "
        "`media` discovers and downloads images/videos/audio from pages. "
        "All web operations are cached for performance."
    ),
    lifespan=_lifespan,
)

# Register the standard `config__open_relay` MCP tool so an LLM can re-trigger
# the relay form when the server is reachable over HTTP. Helper lives in
# mcp-core >=1.13.0b4; signature: (mcp, server_name, public_url). Pass
# ``PUBLIC_URL`` (or ``None`` in stdio mode -> tool returns
# ``status: 'stdio_unsupported'``).
from mcp_core.relay.tool_helpers import register_open_relay_tool  # noqa: E402

register_open_relay_tool(mcp, "wet-mcp", os.environ.get("PUBLIC_URL"))

# Grace period (seconds) given to a cancelled task to clean up resources
# (e.g. close browser tabs) before we abandon it entirely.
_CANCEL_GRACE_PERIOD = 5.0


def _wrap_tool(tool_name: str):
    """Decorator to wrap tool results with XPIA safety markers.

    Encapsulates untrusted external content in XML boundary tags and appends
    a security warning instructing the LLM to treat the content as data only.
    Error responses are passed through unwrapped.
    """

    def decorator(func):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            result = await func(*args, **kwargs)
            return wrap_external_content(tool_name, result)

        return wrapper

    return decorator


# Sub-operation timeouts (seconds) within docs search.
# These prevent any single step from consuming the entire tool_timeout budget.
_SEARXNG_TIMEOUT = 150  # ensure_searxng() — cold start can take 90-120s
_DISCOVERY_TIMEOUT = 30  # discover_library() — registry + probe
_FETCH_TIMEOUT = 90  # _fetch_and_chunk_docs() — llms.txt + GH raw + crawl
_EMBED_TIMEOUT = 60  # _embed_batch() — ONNX for all chunks
_FALLBACK_TIMEOUT = 60  # SearXNG fallback fetch


async def _with_timeout(coro, action: str) -> str:
    """Wrap coroutine with hard timeout.

    Uses ``asyncio.wait`` instead of ``asyncio.wait_for`` because
    Playwright / Crawl4AI may suppress ``CancelledError`` internally,
    causing ``wait_for`` to block indefinitely.  ``asyncio.wait``
    returns immediately when the deadline expires regardless of whether
    the inner task cooperates with cancellation.

    After cancellation the task is given a brief grace period to release
    resources (browser tabs, network connections) before being abandoned.
    """
    timeout = settings.tool_timeout
    if timeout <= 0:
        return await coro

    task = asyncio.create_task(coro)
    done, _pending = await asyncio.wait({task}, timeout=timeout)

    if done:
        # Propagate any exception raised by the task
        return task.result()

    # Hard timeout -- cancel and wait briefly for cleanup
    task.cancel()
    logger.warning(f"Tool '{action}' timed out after {timeout}s, cancelling...")

    # Give the task a grace period to clean up (close browser pages, etc.)
    try:
        await asyncio.wait_for(asyncio.shield(task), timeout=_CANCEL_GRACE_PERIOD)
    except (asyncio.CancelledError, TimeoutError, Exception):
        # Task either cancelled cleanly, timed out again, or raised -- all OK
        pass

    logger.error(f"Tool '{action}' timed out after {timeout}s")
    return (
        f"Error: '{action}' timed out after {timeout}s. "
        "Increase TOOL_TIMEOUT or try simpler parameters."
    )


# ---------------------------------------------------------------------------
# search tool: search, research, docs
# ---------------------------------------------------------------------------


@mcp.tool(
    annotations=ToolAnnotations(
        readOnlyHint=True,
        openWorldHint=True,
        idempotentHint=True,
    ),
)
@_wrap_tool("search")
async def search(  # noqa: PLR0913
    action: str,
    query: str | None = None,
    library: str | None = None,
    version: str | None = None,
    topic: str | None = None,
    project_path: str | None = None,
    language: str | None = None,
    categories: str = "general",
    max_results: int = 10,
    limit: int = 10,
    time_range: str | None = None,
    include_domains: list[str] | None = None,
    exclude_domains: list[str] | None = None,
    expand: bool = False,
    enrich: bool = False,
) -> str:
    """Find information across web, academic sources, or library docs. Returns search result listings (titles, URLs, snippets) -- NOT full page content. To read full content from a URL, use the `extract` tool instead.

    Actions:
    - search: Web search via SearXNG. Example: search(action="search", query="python async patterns")
    - research: Academic/scientific search (Google Scholar, arXiv, PubMed). Example: search(action="research", query="transformer attention mechanism")
    - docs: Search library documentation with auto-indexing. Example: search(action="docs", query="how to create routes", library="fastapi")
    - docs_resolve: Free-form library name to ranked library_id list. Example: search(action="docs_resolve", query="react")
    - docs_query: Version-aware library docs query honoring project lock + token cap. Example: search(action="docs_query", library="react", version="latest", topic="useState", query="how to set initial state")
    - docs_lock_project: Detect project manifests (pyproject/package.json/go.mod/Cargo.toml) and lock the library set for Cabinets isolation. Example: search(action="docs_lock_project", project_path="/repo/my-app")
    - similar: Find pages similar to a URL (pass URL as query). Example: search(action="similar", query="https://example.com/article")

    Key parameters:
    - query (required for all actions): Search terms or URL (for similar)
    - library (required for docs): Library name, e.g. "react", "fastapi"
    - language: Programming language for disambiguation in docs, e.g. "python", "java"
    - expand: Enable LLM query expansion for broader coverage (default: false)
    - enrich: Fetch actual page content for richer snippets (default: false, adds latency)
    - max_results: Number of results (default: 10)
    - time_range: Recency filter -- day, week, month, year
    - include_domains / exclude_domains: Domain filters

    Use `help` tool with tool_name="search" for full parameter documentation.
    """
    blocked = _require_credentials()
    if blocked:
        return blocked

    # Stdio uvx tool venv lacks pip, so the web-core SearXNG runner cannot
    # install/start a local SearXNG instance, and its hardcoded
    # ``localhost:8080`` fallback is wrong for our pinned Docker port.
    # Per spec ``2026-05-01-stdio-pure-http-multiuser.md`` §4.1.1, reject
    # SearXNG-dependent actions with a clear error pointing at Method 3
    # (stdio Docker) or Method 2 (HTTP Docker). Other actions on the
    # ``extract`` tool (``extract`` / ``crawl`` / ``map`` / ``media``) hit
    # upstream via ``httpx`` directly and remain available.
    # docs_resolve and docs_lock_project do not need SearXNG (pure DB ops);
    # docs_query falls back to local FTS even without SearXNG, so allow it.
    if action in ("search", "research", "docs", "similar") and is_uvx_tool_venv():
        return uvx_searxng_blocked_error(action)

    match action:
        case "search":
            if not query:
                return 'Error: query is required for search action. Example: search(action="search", query="python async patterns")'
            from wet_mcp.sources._search_polish import (
                normalize_query,
                search_ttl_seconds,
                standardize_results,
            )

            normalized_query = normalize_query(query)
            ttl = search_ttl_seconds(time_range)
            cache_params = {
                "query": normalized_query,
                "categories": categories,
                "max_results": max_results,
                "time_range": time_range,
                "language": language,
                "include_domains": include_domains,
                "exclude_domains": exclude_domains,
            }
            if _web_cache:
                cache_hit = await asyncio.to_thread(
                    _web_cache.get_with_age, "search", cache_params
                )
                if cache_hit:
                    cached_content, cache_age = cache_hit
                    # Re-stamp freshness signal based on current age.
                    try:
                        cached_data = json.loads(cached_content)
                        if isinstance(cached_data, dict) and cached_data.get("results"):
                            cached_data["results"] = standardize_results(
                                cached_data["results"],
                                cache_age_seconds=cache_age,
                                ttl_seconds=ttl,
                            )
                            return json.dumps(cached_data, ensure_ascii=False, indent=2)
                    except json.JSONDecodeError:
                        pass
                    return cached_content
            try:
                searxng_url = await asyncio.wait_for(
                    ensure_searxng(), timeout=_SEARXNG_TIMEOUT
                )
            except TimeoutError:
                return f"Error: SearXNG startup timed out ({_SEARXNG_TIMEOUT}s). Try again or check logs."
            except (SystemExit, Exception) as exc:
                return f"Error: SearXNG startup failed: {exc}"
            # Optional query expansion (LLM-driven, opt-in)
            search_query = normalized_query or query
            if expand:
                from wet_mcp.sources.search_strategies import expand_query

                expanded = await expand_query(query)
                if len(expanded) > 1:
                    search_query = " OR ".join(expanded)

            result = await _with_timeout(
                searxng_search(
                    searxng_url=searxng_url,
                    query=search_query,
                    categories=categories,
                    max_results=max_results * _RERANK_CANDIDATE_MULTIPLIER,
                    time_range=time_range,
                    language=language,
                    include_domains=include_domains,
                    exclude_domains=exclude_domains,
                ),
                "search",
            )
            if not result.startswith("Error"):
                try:
                    data = json.loads(result)
                    modified = False

                    # Rerank by semantic relevance (same as research/docs)
                    try:
                        results_list = data.get("results", [])
                        if results_list:
                            # Map snippet -> content for reranker (fallback to title)
                            for r in results_list:
                                if "content" not in r:
                                    r["content"] = r.get("snippet", r.get("title", ""))
                            reranked = await _rerank_results(
                                query, results_list, top_n=max_results
                            )
                            if reranked:
                                data["results"] = [
                                    r for r in reranked if r.get("score", 1.0) > 0.2
                                ]
                                data["total"] = len(data["results"])
                                modified = True
                    except Exception as e:
                        logger.debug(f"Search reranking failed, using original: {e}")

                    # Optional snippet enrichment
                    if enrich:
                        try:
                            results_list = data.get("results", [])
                            if results_list:
                                from wet_mcp.sources.search_strategies import (
                                    enrich_snippets,
                                )

                                enriched = await enrich_snippets(
                                    results_list, query, top_n=5
                                )
                                data["results"] = enriched
                                modified = True
                        except Exception as e:
                            logger.debug(f"Snippet enrichment failed: {e}")

                    # Citation standardization (always on -- cheap pure-python).
                    try:
                        results_list = data.get("results", [])
                        if results_list:
                            data["results"] = standardize_results(
                                results_list,
                                cache_age_seconds=None,
                                ttl_seconds=ttl,
                            )
                            modified = True
                    except Exception as e:
                        logger.debug(f"Citation standardization failed: {e}")

                    if modified:
                        result = json.dumps(data, ensure_ascii=False, indent=2)
                except json.JSONDecodeError:
                    pass
            if _web_cache and not result.startswith("Error"):
                await asyncio.to_thread(
                    _web_cache.set, "search", cache_params, result, ttl
                )
            return result

        case "research":
            if not query:
                return 'Error: query is required for research action. Example: search(action="research", query="transformer attention mechanism")'
            cache_params = {
                "query": query,
                "max_results": max_results,
                "time_range": time_range,
                "language": language,
                "include_domains": include_domains,
                "exclude_domains": exclude_domains,
            }
            if _web_cache:
                cached = await asyncio.to_thread(
                    _web_cache.get, "research", cache_params
                )
                if cached:
                    return cached
            result = await _with_timeout(
                _do_research(
                    query=query,
                    max_results=max_results,
                    time_range=time_range,
                    language=language,
                    include_domains=include_domains,
                    exclude_domains=exclude_domains,
                ),
                "research",
            )
            if _web_cache and not result.startswith("Error"):
                await asyncio.to_thread(
                    _web_cache.set, "research", cache_params, result
                )
            return result

        case "docs":
            if not library:
                return 'Error: library is required for docs action. Example: search(action="docs", query="routing", library="fastapi")'
            if not query:
                return 'Error: query is required for docs action. Example: search(action="docs", query="how to create routes", library="fastapi")'
            return await _with_timeout(
                _do_docs_search(
                    library=library,
                    query=query,
                    language=language,
                    version=version,
                    limit=limit,
                ),
                "docs",
            )

        case "similar":
            if not query:
                return 'Error: query (URL) is required for similar action. Example: search(action="similar", query="https://example.com/article")'
            if not query.startswith(("http://", "https://")):
                return 'Error: query must be a full URL starting with http:// or https://. Example: search(action="similar", query="https://example.com/article"). If you want to search by keywords instead, use action="search".'
            try:
                searxng_url = await asyncio.wait_for(
                    ensure_searxng(), timeout=_SEARXNG_TIMEOUT
                )
            except (TimeoutError, SystemExit, Exception) as exc:
                return f"Error: SearXNG startup failed: {exc}"
            from wet_mcp.sources.search_strategies import find_similar

            return await _with_timeout(
                find_similar(
                    url=query, max_results=max_results, searxng_url=searxng_url
                ),
                "similar",
            )

        case "docs_resolve":
            if not query:
                return 'Error: query (library name) is required for docs_resolve. Example: search(action="docs_resolve", query="react")'
            if not _docs_db:
                return "Error: Docs database not initialized"
            from wet_mcp.sources.docs import resolve_library

            results = await asyncio.to_thread(resolve_library, _docs_db, query, limit)
            return json.dumps(
                {"query": query, "results": results, "total": len(results)},
                ensure_ascii=False,
                indent=2,
            )

        case "docs_query":
            if not query:
                return 'Error: query is required for docs_query. Example: search(action="docs_query", library="react", query="useState")'
            if not library:
                return 'Error: library is required for docs_query. Example: search(action="docs_query", library="react", query="useState")'
            if not _docs_db:
                return "Error: Docs database not initialized"
            from wet_mcp.sources.docs import (
                ingest_tier2,
                query_docs,
                resolve_library,
            )

            # Resolve library: accept either library_id (12-char hex) or
            # canonical/alias name. We always look up by name first so the
            # caller can pass either form.
            resolved = await asyncio.to_thread(resolve_library, _docs_db, library, 1)
            if not resolved:
                # Tier 2 lazy ingest: fire-and-forget, return progress hint.
                asyncio.create_task(ingest_tier2(_docs_db, library))
                return json.dumps(
                    {
                        "status": "indexing_in_progress",
                        "library": library,
                        "message": (
                            "Library not yet indexed. Tier 2 ingestion has "
                            "started in the background; retry shortly."
                        ),
                        "results": [],
                    },
                    ensure_ascii=False,
                    indent=2,
                )

            lib_id = resolved[0]["library_id"]
            effective_version = version

            # Honor Cabinets project lock when project_path is supplied AND
            # the caller did not explicitly pin a version.
            lock_pin: str | None = None
            if project_path and not version:
                lock_entry = await asyncio.to_thread(
                    _docs_db.get_project_context, project_path
                )
                if lock_entry:
                    for locked in lock_entry.get("locked_libraries", []):
                        if locked.get("id") in (lib_id, library, library.lower()):
                            lock_pin = locked.get("version")
                            break
                    await asyncio.to_thread(
                        _docs_db.touch_project_context, project_path
                    )
            if lock_pin:
                effective_version = lock_pin

            results = await asyncio.to_thread(
                query_docs,
                _docs_db,
                lib_id,
                query,
                effective_version,
                topic,
                limit,
            )
            return json.dumps(
                {
                    "library": resolved[0],
                    "query": query,
                    "version": effective_version or "latest",
                    "topic": topic,
                    "project_path": project_path,
                    "lock_pin": lock_pin,
                    "results": results,
                    "total": len(results),
                },
                ensure_ascii=False,
                indent=2,
            )

        case "docs_lock_project":
            if not project_path:
                return 'Error: project_path is required for docs_lock_project. Example: search(action="docs_lock_project", project_path="/repo/my-app")'
            if not _docs_db:
                return "Error: Docs database not initialized"
            from wet_mcp.sources.project_lock import lock_project

            try:
                lock = await asyncio.to_thread(
                    lock_project, _docs_db, Path(project_path)
                )
            except FileNotFoundError as exc:
                return f"Error: project_path does not exist: {exc}"
            return json.dumps(lock, ensure_ascii=False, indent=2)

        case _:
            import difflib

            valid_actions = [
                "docs",
                "docs_resolve",
                "docs_query",
                "docs_lock_project",
                "research",
                "search",
                "similar",
            ]
            closest = (
                difflib.get_close_matches(action, valid_actions, n=1)
                if action is not None
                else []
            )
            suggestion = f" Did you mean '{closest[0]}'?" if closest else ""
            return (
                f"Error: Unknown action '{action}'.{suggestion} "
                "Valid actions: search (web search), research (academic), "
                "docs (library documentation, auto-indexing), "
                "docs_resolve (library name → ranked library_id), "
                "docs_query (version-aware docs query with token cap), "
                "docs_lock_project (Cabinets project isolation), "
                "similar (find related pages). "
                "If you want to read content from a URL, use the `extract` tool instead."
            )


# ---------------------------------------------------------------------------
# extract tool: extract, crawl, map
# ---------------------------------------------------------------------------


@mcp.tool(
    annotations=ToolAnnotations(
        readOnlyHint=True,
        openWorldHint=True,
    ),
)
@_wrap_tool("extract")
async def extract(  # noqa: PLR0913
    action: str,
    urls: list[str] | None = None,
    paths: list[str] | None = None,
    depth: int = 2,
    max_pages: int = 20,
    format: str = "markdown",
    stealth: bool = False,
    schema: dict | None = None,
    prompt: str | None = None,
    query: str | None = None,
    max_urls: int = 5,
    synthesis_model: str | None = None,
    token_budget: int = 10000,
    actions: list[dict] | None = None,
    session: str | None = None,
    screenshot: bool = False,
    url: str | None = None,
) -> str:
    """Read and return full page content from URLs or local files. Use this when you
    have a specific URL and need its content. For finding URLs first, use the
    `search` tool instead.

    Actions:
    - extract: Get clean content from URLs.
      Example: extract(action="extract", urls=["https://example.com/article"])
    - batch: Batch extract with per-domain rate limiting (max 50 URLs).
      Example: extract(action="batch", urls=["https://a.com/1", "https://b.com/2"])
    - crawl: Deep crawl following links from root URLs.
      Example: extract(action="crawl", urls=["https://docs.example.com"], depth=2)
    - map: Discover site URL structure without extracting content.
      Example: extract(action="map", urls=["https://example.com"])
    - convert: Convert local files (PDF, DOCX, PPTX, XLSX) to Markdown.
      Example: extract(action="convert", paths=["/home/user/report.pdf"])
    - extract_structured: Extract structured data using JSON Schema + LLM.
      Example: extract(action="extract_structured",
      urls=["https://example.com/pricing"],
      schema={"type": "object", "properties": {"price": {"type": "string"}}})
    - agent: Multi-step research orchestration -- search the web, extract top
      results, synthesize a cited Markdown answer.
      Example: extract(action="agent", query="latest pydantic 2 changes",
      max_urls=5)
    - interact: Drive a page with click/fill/submit via patchright.
      Example: extract(action="interact", url="https://example.com/login",
      actions=[{"type": "fill", "selector": "#email", "value": "x@y.com"},
      {"type": "submit", "selector": "form"}])

    Key parameters:
    - urls (required for extract/batch/crawl/map/extract_structured): List of URLs
    - paths (required for convert): List of local file paths
    - query (required for agent): Research question to answer
    - url (required for interact): Page URL to drive
    - actions (required for interact): List of {type, selector?, description?,
      value?} ops
    - max_urls (agent): Default 5, hard cap 20
    - synthesis_model (agent): Override LLM model for the synthesis step
    - token_budget (agent): Max prompt tokens (default 10000)
    - session (interact): Persistent session id; reuses browser across calls
    - screenshot (interact): Capture post-interaction screenshot
    - format: Output format -- "markdown" (default), "text", "html"
    - depth: Crawl depth (default: 2, max: 5)
    - max_pages: Max pages for crawl/map (default: 20, max: 100)
    - stealth: Enable anti-bot bypass for protected sites (default: false)
    - schema: JSON Schema dict for extract_structured

    Use `help` tool with tool_name="extract" for full parameter documentation.
    """
    # Security: enforce hard limits to prevent resource exhaustion
    _MAX_EXTRACT_URLS = 20
    _MAX_CRAWL_PAGES = 100
    _MAX_DEPTH = 5

    blocked = _require_credentials()
    if blocked:
        return blocked

    max_pages = min(max_pages, _MAX_CRAWL_PAGES)
    depth = min(depth, _MAX_DEPTH)

    match action:
        case "extract":
            if not urls:
                return 'Error: urls is required for extract action. Example: extract(action="extract", urls=["https://example.com/page"])'
            urls = urls[:_MAX_EXTRACT_URLS]
            cache_params = {"urls": sorted(urls), "format": format, "stealth": stealth}
            if _web_cache:
                cached = await asyncio.to_thread(
                    _web_cache.get, "extract", cache_params
                )
                if cached:
                    return cached
            result = await _with_timeout(
                _extract(urls=urls, format=format, stealth=stealth),
                "extract",
            )
            if _web_cache and not result.startswith("Error"):
                await asyncio.to_thread(_web_cache.set, "extract", cache_params, result)
            return result

        case "batch":
            if not urls:
                return 'Error: urls is required for batch action. Example: extract(action="batch", urls=["https://a.com/1", "https://b.com/2"])'
            from wet_mcp.sources.crawler import batch_extract

            return await _with_timeout(
                batch_extract(urls=urls, format=format, stealth=stealth),
                "batch",
            )

        case "crawl":
            if not urls:
                return 'Error: urls is required for crawl action. Example: extract(action="crawl", urls=["https://docs.example.com"], depth=2)'
            urls = urls[:_MAX_EXTRACT_URLS]
            cache_params = {
                "urls": sorted(urls),
                "depth": depth,
                "max_pages": max_pages,
            }
            if _web_cache:
                cached = await asyncio.to_thread(_web_cache.get, "crawl", cache_params)
                if cached:
                    return cached
            result = await _with_timeout(
                _crawl(
                    urls=urls,
                    depth=depth,
                    max_pages=max_pages,
                    format=format,
                    stealth=stealth,
                ),
                "crawl",
            )
            if _web_cache and not result.startswith("Error"):
                await asyncio.to_thread(_web_cache.set, "crawl", cache_params, result)
            return result

        case "map":
            if not urls:
                return 'Error: urls is required for map action. Example: extract(action="map", urls=["https://example.com"])'
            urls = urls[:_MAX_EXTRACT_URLS]
            cache_params = {
                "urls": sorted(urls),
                "depth": depth,
                "max_pages": max_pages,
            }
            if _web_cache:
                cached = await asyncio.to_thread(_web_cache.get, "map", cache_params)
                if cached:
                    return cached
            result = await _with_timeout(
                _sitemap(urls=urls, depth=depth, max_pages=max_pages),
                "map",
            )
            if _web_cache and not result.startswith("Error"):
                await asyncio.to_thread(_web_cache.set, "map", cache_params, result)
            return result

        case "convert":
            if not paths:
                return 'Error: paths is required for convert action. Example: extract(action="convert", paths=["/home/user/report.pdf"])'
            from wet_mcp.sources.crawler import convert_local_files

            return await _with_timeout(
                convert_local_files(paths=paths),
                "convert",
            )

        case "extract_structured":
            if not urls:
                return 'Error: urls is required for extract_structured action. Example: extract(action="extract_structured", urls=["https://example.com/pricing"], schema={"type": "object", "properties": {"price": {"type": "string"}}})'
            if not schema:
                return 'Error: schema (JSON Schema dict) is required for extract_structured action. Provide a JSON Schema defining the data structure to extract. Example: schema={"type": "object", "properties": {"title": {"type": "string"}, "items": {"type": "array", "items": {"type": "object"}}}}'
            from wet_mcp.sources.structured import extract_structured

            return await _with_timeout(
                extract_structured(
                    urls=urls, schema=schema, prompt=prompt, stealth=stealth
                ),
                "extract_structured",
            )

        case "agent":
            if not query:
                return 'Error: query is required for agent action. Example: extract(action="agent", query="latest pydantic 2 changes", max_urls=5)'
            from wet_mcp.sources.agent_orchestrator import run_agent

            result = await _with_timeout(
                run_agent(
                    query=query,
                    max_urls=max_urls,
                    synthesis_model=synthesis_model,
                    token_budget=token_budget,
                ),
                "agent",
            )
            if isinstance(result, str):
                return result
            return json.dumps(result, ensure_ascii=False, indent=2)

        case "interact":
            if not url:
                return 'Error: url is required for interact action. Example: extract(action="interact", url="https://example.com/login", actions=[{"type": "click", "selector": "#submit"}])'
            if not actions:
                return 'Error: actions is required for interact action. Provide a list of {type, selector?, description?, value?} ops. Example: actions=[{"type": "fill", "selector": "#email", "value": "x@y.com"}, {"type": "submit", "selector": "form"}]'
            from wet_mcp.sources.interact_orchestrator import run_interact

            result = await _with_timeout(
                run_interact(
                    url=url,
                    actions=actions,
                    session=session,
                    screenshot=screenshot,
                ),
                "interact",
            )
            if isinstance(result, str):
                return result
            return json.dumps(result, ensure_ascii=False, indent=2)

        case _:
            import difflib

            valid_actions = [
                "agent",
                "batch",
                "convert",
                "crawl",
                "extract",
                "extract_structured",
                "interact",
                "map",
            ]
            closest = (
                difflib.get_close_matches(action, valid_actions, n=1)
                if action is not None
                else []
            )
            suggestion = f" Did you mean '{closest[0]}'?" if closest else ""
            return (
                f"Error: Unknown action '{action}'.{suggestion} "
                "Valid actions: extract (read URL content), batch (bulk extract), crawl (follow links), "
                "map (site structure), convert (local files to markdown), extract_structured (schema-based), "
                "agent (multi-step research orchestration), interact (drive a page with click/fill/submit). "
                "If you want to search for information, use the `search` tool instead."
            )


@mcp.tool(
    annotations=ToolAnnotations(
        readOnlyHint=False,
        openWorldHint=True,
    ),
)
@_wrap_tool("media")
async def media(  # noqa: PLR0913
    action: str,
    url: str | None = None,
    media_type: str = "all",
    media_urls: list[str] | None = None,
    output_dir: str | None = None,
    max_items: int = 10,
    prompt: str = "Describe this image in detail.",
) -> str:
    """Discover and download media files (images, videos, audio) from web pages.

    Actions:
    - list: Scan a page and return media URLs with metadata. Example: media(action="list", url="https://example.com/gallery", media_type="images")
    - download: Download media files to local storage. Example: media(action="download", media_urls=["https://example.com/photo.jpg"])

    Key parameters:
    - url (required for list): Page URL to scan
    - media_urls (required for download): List of media URLs to download
    - media_type: Filter for list -- "images", "videos", "audio", "files", "all" (default: "all")
    - output_dir: Download directory (default: ~/.wet-mcp/downloads)
    - prompt: Reserved -- accepted for backward compatibility, ignored

    Typical workflow: list (discover) -> download (save locally). For LLM
    analysis (vision/audio/video), hand the downloaded path to
    imagine-mcp's understand action. The legacy media(action="analyze")
    was REMOVED in wet v2.0.0 (deprecated since v1.x.y); calling it now
    returns the standard unknown-action error.

    Use `help` tool with tool_name="media" for full documentation.
    """
    blocked = _require_credentials()
    if blocked:
        return blocked

    from wet_mcp.sources.crawler import download_media

    match action:
        case "list":
            if not url:
                return 'Error: url is required for list action. Example: media(action="list", url="https://example.com/gallery", media_type="images")'
            return await _with_timeout(
                list_media(url=url, media_type=media_type, max_items=max_items),
                "media.list",
            )

        case "download":
            if not media_urls:
                return 'Error: media_urls is required for download action. Example: media(action="download", media_urls=["https://example.com/image.jpg"]). Use media(action="list", url="...") first to discover media URLs.'

            # Security: validate output_dir is within the configured
            # download directory to prevent arbitrary file writes.
            resolved_download_dir = Path(settings.download_dir).expanduser().resolve()
            target_dir = (
                Path(output_dir or settings.download_dir).expanduser().resolve()
            )
            if not target_dir.is_relative_to(resolved_download_dir):
                return (
                    "Error: Security Alert — output_dir must be within "
                    f"the configured download directory ({resolved_download_dir})"
                )

            return await _with_timeout(
                download_media(
                    media_urls=media_urls,
                    output_dir=str(target_dir),
                ),
                "media.download",
            )

        case _:
            import difflib

            # Phase 3 (v2.0.0) BREAKING: analyze removed entirely after the
            # 2-minor-version deprecation grace period started in Phase 1
            # commit 2ea6f23. Vision/audio/video analysis lives in
            # imagine-mcp's understand action. We special-case the
            # message for callers still passing analyze so they can
            # migrate without hunting through release notes.
            valid_actions = ["download", "list"]
            closest = (
                difflib.get_close_matches(action, valid_actions, n=1)
                if action is not None
                else []
            )
            suggestion = f" Did you mean '{closest[0]}'?" if closest else ""
            if action == "analyze":
                return (
                    "Error: Unknown action 'analyze'. The analyze action was "
                    "removed in wet v2.0.0. Use imagine-mcp's understand "
                    "action for vision/audio/video analysis. "
                    "Valid wet media actions: list (discover media on page), "
                    "download (save to local)."
                )
            return (
                f"Error: Unknown action '{action}'.{suggestion} "
                "Valid actions: list (discover media on page), "
                "download (save to local)."
            )


@mcp.tool(
    annotations=ToolAnnotations(
        readOnlyHint=True,
        openWorldHint=False,
        idempotentHint=True,
    ),
)
async def help(tool_name: str = "search") -> str:
    """Get detailed documentation for any tool. Call this when you need full parameter reference or usage examples.

    Valid tool_name values: search, extract, media, config.

    Quick guide -- which tool to use:
    - Need to FIND information? Use `search` (returns result listings with URLs)
    - Need to READ a page? Use `extract` (returns full page content from a URL)
    - Need media files? Use `media` (discover, download images/videos/audio)
    - Need server settings? Use `config` (status, cache, settings, warmup, sync setup)
    """
    allowed_tools = {"search", "extract", "media", "config"}
    if tool_name not in allowed_tools:
        import difflib

        closest = (
            difflib.get_close_matches(tool_name, sorted(allowed_tools), n=1)
            if tool_name is not None
            else []
        )
        suggestion = f" Did you mean '{closest[0]}'?" if closest else ""
        return f"Error: Invalid tool_name '{tool_name}'.{suggestion} Valid options: {', '.join(sorted(allowed_tools))}."

    try:
        doc_file = files("wet_mcp.docs").joinpath(f"{tool_name}.md")
        return doc_file.read_text()
    except FileNotFoundError:
        return f"Error: No documentation found for tool '{tool_name}'"
    except Exception as e:
        return f"Error loading documentation: {e}"


async def _handle_config_status() -> str:
    from wet_mcp.embedder import get_backend
    from wet_mcp.reranker import get_reranker

    embed_backend = get_backend()
    reranker = get_reranker()

    status = {
        "database": {
            "path": str(settings.get_db_path()),
            "docs_indexed": (_docs_db.stats() if _docs_db else {}),
        },
        "embedding": {
            "backend": (type(embed_backend).__name__ if embed_backend else None),
            "dims": _embedding_dims,
            "available": embed_backend is not None,
        },
        "reranker": {
            "available": reranker is not None,
            "backend": (type(reranker).__name__ if reranker else None),
        },
        "cache": {
            "enabled": settings.wet_cache,
            "path": (str(settings.get_cache_db_path()) if settings.wet_cache else None),
        },
        "sync": {
            "enabled": settings.sync_enabled,
            "provider": "google_drive",
            "folder": settings.sync_folder,
            "interval": settings.sync_interval,
            "google_drive_client_id": bool(settings.google_drive_client_id),
        },
        "settings": {
            "log_level": settings.log_level,
            "tool_timeout": settings.tool_timeout,
        },
    }
    return json.dumps(status, indent=2, default=str)


def _handle_config_set(key: str | None, value: str | None) -> str:
    if not key or value is None:
        return json.dumps({"error": "key and value are required for set"})
    valid_keys = {
        "log_level",
        "tool_timeout",
        "wet_cache",
        "sync_enabled",
        "sync_folder",
        "sync_interval",
    }
    if key not in valid_keys:
        import difflib

        closest = (
            difflib.get_close_matches(key, sorted(valid_keys), n=1)
            if key is not None
            else []
        )
        suggestion = f" Did you mean '{closest[0]}'?" if closest else ""
        return json.dumps(
            {
                "error": f"Invalid key: {key}.{suggestion}",
                "valid_keys": sorted(valid_keys),
            }
        )
    if key == "log_level":
        settings.log_level = value.upper()
        logger.remove()
        logger.add(sys.stderr, level=settings.log_level)
    elif key in ("tool_timeout", "sync_interval"):
        setattr(settings, key, int(value))
    elif key in ("wet_cache", "sync_enabled"):
        setattr(settings, key, value.lower() in ("true", "1", "yes"))
    else:
        setattr(settings, key, value)
    return json.dumps(
        {
            "status": "updated",
            "key": key,
            "value": getattr(settings, key),
        },
        default=str,
    )


async def _handle_config_cache_clear() -> str:
    if _web_cache:
        await asyncio.to_thread(_web_cache.clear)
        return json.dumps({"status": "cache cleared"})
    return json.dumps({"error": "Cache is not enabled"})


def _handle_config_docs_reindex(key: str | None) -> str:
    if not key:
        return json.dumps({"error": "key (library name) is required"})
    if not _docs_db:
        return json.dumps({"error": "Docs database not initialized"})
    lib = _docs_db.get_library(key)
    if lib:
        ver = _docs_db.get_best_version(lib["id"])
        if ver:
            _docs_db.clear_version_chunks(ver["id"])
        return json.dumps(
            {
                "status": "cleared",
                "library": key,
                "hint": "Next docs search will re-index",
            }
        )
    return json.dumps({"error": f"Library '{key}' not found in index"})


async def _handle_config_warmup() -> str:
    from wet_mcp.setup_tool import run_warmup

    result = await run_warmup()
    return json.dumps(result, indent=2, default=str)


async def _handle_config_setup_sync(remote_type: str | None) -> str:
    from wet_mcp.setup_tool import run_setup_sync

    result = await run_setup_sync(remote_type or "drive")
    return json.dumps(result, indent=2, default=str)


def _handle_config_setup_status() -> str:
    from mcp_core.storage.per_plugin_store import PerPluginStore

    from wet_mcp import credential_state as _cs

    _saved = PerPluginStore(_cs.PLUGIN_NAME).load() or {}
    _env_keys = [k for k in _cs.CLOUD_KEYS if os.environ.get(k)]
    _store_keys = [k for k in _cs.CLOUD_KEYS if _saved.get(k)]
    _providers = list(dict.fromkeys(_env_keys + _store_keys))
    if _providers:
        _derived_state = "configured"
    elif _cs.get_state() == _cs.CredentialState.LOCAL:
        _derived_state = "local"
    else:
        _derived_state = "awaiting_setup"
    return json.dumps(
        {
            "state": _derived_state,
            "setup_url": _cs.get_setup_url(),
            "cloud_keys_in_env": _env_keys,
            "providers_configured": _providers,
        }
    )


def _handle_config_setup_skip() -> str:
    from mcp_core import set_local_mode

    from wet_mcp.credential_state import CredentialState, set_state

    set_local_mode("wet-mcp")
    set_state(CredentialState.LOCAL)
    return json.dumps(
        {
            "status": "ok",
            "message": "Local mode set. Relay will not trigger on restart.",
        }
    )


def _handle_config_setup_reset() -> str:
    from wet_mcp.credential_state import reset_state

    reset_state()
    return json.dumps(
        {
            "status": "ok",
            "message": "Credentials cleared. Next tool call will offer setup.",
        }
    )


async def _handle_config_setup_complete() -> str:
    from wet_mcp.credential_state import (
        CredentialState,
        resolve_credential_state,
    )
    from wet_mcp.credential_state import (
        get_state as _get_state,
    )

    resolve_credential_state()
    state = _get_state()
    mode = settings.setup_providers()

    # Re-init embedding + reranker if now configured
    if state == CredentialState.CONFIGURED:
        await _init_embedding_backend(mode)
        await _init_reranker_backend(mode)

    return json.dumps(
        {
            "status": "ok",
            "state": state.value,
            "message": "Credential state refreshed.",
        }
    )


@mcp.tool(
    description=(
        "Server config and management. Actions: "
        "status|set|cache_clear|docs_reindex|warmup|setup_sync|"
        "setup_status|setup_skip|setup_reset|setup_complete. "
        "Use help tool with tool_name='config' for full docs."
    ),
    annotations=ToolAnnotations(
        title="Config",
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=True,
    ),
)
async def config(
    action: str,
    key: str | None = None,
    value: str | None = None,
    remote_type: str | None = None,
    force: bool = False,
) -> str:
    """Server configuration and management.

    Actions:
    - status: Show current config and status
    - set: Update runtime setting (key + value required)
    - cache_clear: Clear web cache
    - docs_reindex: Force re-index a library (key = library name)
    - warmup: Pre-download models and run first-time setup
    - setup_sync: Configure Google Drive sync (OAuth Device Code flow)
    - setup_status: Show current credential state and configured keys
    - setup_skip: Use local ONNX models (explicit opt-in, no cloud features)
    - setup_reset: Clear all credentials and reset state
    - setup_complete: Re-resolve credentials from environment
    """
    match action:
        case "status":
            return await _handle_config_status()

        case "set":
            return _handle_config_set(key, value)

        case "cache_clear":
            return await _handle_config_cache_clear()

        case "docs_reindex":
            return _handle_config_docs_reindex(key)

        case "warmup":
            return await _handle_config_warmup()

        case "setup_sync":
            return await _handle_config_setup_sync(remote_type)

        case "setup_status":
            return _handle_config_setup_status()

        case "setup_skip":
            return _handle_config_setup_skip()

        case "setup_reset":
            return _handle_config_setup_reset()

        case "setup_complete":
            return await _handle_config_setup_complete()

        case _:
            import difflib

            valid_actions = [
                "cache_clear",
                "docs_reindex",
                "set",
                "setup_complete",
                "setup_reset",
                "setup_skip",
                "setup_status",
                "setup_sync",
                "status",
                "warmup",
            ]
            closest = (
                difflib.get_close_matches(action, valid_actions, n=1)
                if action is not None
                else []
            )
            suggestion = f" Did you mean '{closest[0]}'?" if closest else ""
            return json.dumps(
                {
                    "error": f"Unknown action '{action}'.{suggestion}",
                    "valid_actions": valid_actions,
                }
            )


# ---------------------------------------------------------------------------
# Research (academic search via SearXNG science category)
# ---------------------------------------------------------------------------
async def _do_research(
    query: str,
    max_results: int = 10,
    time_range: str | None = None,
    language: str | None = None,
    include_domains: list[str] | None = None,
    exclude_domains: list[str] | None = None,
) -> str:
    """Academic/scientific search using SearXNG science engines."""
    try:
        searxng_url = await asyncio.wait_for(ensure_searxng(), timeout=_SEARXNG_TIMEOUT)
    except TimeoutError:
        return f"Error: SearXNG startup timed out ({_SEARXNG_TIMEOUT}s). Try again or check logs."
    except (SystemExit, Exception) as exc:
        return f"Error: SearXNG startup failed: {exc}"

    result_str = await searxng_search(
        searxng_url=searxng_url,
        query=query,
        categories="science",
        max_results=max_results * 3,
        time_range=time_range,
        language=language,
        include_domains=include_domains,
        exclude_domains=exclude_domains,
    )
    try:
        data = json.loads(result_str)

        # Rerank
        try:
            if "results" in data and data["results"]:
                reranked = await _rerank_results(
                    query, data["results"], top_n=max_results
                )
                data["results"] = [r for r in reranked if r.get("score", 1.0) > 0.3]
                data["total"] = len(data["results"])
        except Exception as e:
            logger.error(f"Reranking failed: {e}")

        # Re-format results for academic context
        results = data.get("results", [])

        # Enrich with academic metadata hints
        SOURCE_TYPE_MAPPING = {
            "arxiv.org": "arxiv",
            "scholar.google": "google_scholar",
            "semanticscholar.org": "semantic_scholar",
            "pubmed": "pubmed",
            "nih.gov": "pubmed",
            "doi.org": "doi",
        }
        for r in results:
            url = r.get("url", "")
            r["source_type"] = next(
                (
                    source_type
                    for domain, source_type in SOURCE_TYPE_MAPPING.items()
                    if domain in url
                ),
                "academic",
            )

        data["query"] = query
        data["search_type"] = "academic"
        return json.dumps(data, ensure_ascii=False, indent=2)
    except json.JSONDecodeError:
        return result_str


# ---------------------------------------------------------------------------
# Docs helpers (extracted from _do_docs_search for clarity)
# ---------------------------------------------------------------------------

# Minimum number of chunks required from llms.txt or GitHub raw docs.
# If fewer are produced, the tier is skipped in favor of crawling.
_MIN_GH_CHUNKS = 20


async def _fetch_and_chunk_docs(
    docs_url: str,
    repo_url: str = "",
    query: str = "",
    library_hint: str = "",
) -> tuple[list[dict], int]:
    """Fetch library documentation and split into searchable chunks.

    Tries content sources in priority order:
    1. llms.txt / llms-full.txt (fastest, AI-optimized)
    2. GitHub raw markdown (clean, no JS rendering needed)
    3. Crawl4AI page crawling (rendered HTML -> markdown)

    Returns:
        Tuple of (chunks, page_count).
    """
    from wet_mcp.sources.docs import (
        _try_github_raw_docs,
        chunk_llms_txt,
        chunk_markdown,
        fetch_docs_pages,
        try_llms_txt,
    )

    # Tier 0: Try llms.txt (fastest, best quality)
    llms_content = await try_llms_txt(docs_url)
    if llms_content:
        chunks = chunk_llms_txt(llms_content, base_url=docs_url)
        # Quality gate: skip llms.txt if it's too small (likely a TOC/meta file)
        if len(chunks) >= _MIN_GH_CHUNKS:
            logger.info(f"Indexed {len(chunks)} chunks from llms.txt")
            return chunks, 1
        else:
            logger.info(
                f"llms.txt produced only {len(chunks)} chunks "
                f"(min {_MIN_GH_CHUNKS}), falling through"
            )

    async def _process_page(page: dict) -> list[dict]:
        p_chunks = await asyncio.to_thread(
            chunk_markdown,
            content=page["content"],
            url=page.get("url", ""),
        )
        for chunk in p_chunks:
            if not chunk.get("title") and page.get("title"):
                chunk["title"] = page["title"]
        return p_chunks

    # Tier 1: Try GitHub raw markdown (clean content, no JS rendering)
    gh_target = repo_url or docs_url
    gh_pages = await _try_github_raw_docs(
        gh_target, max_files=50, library_hint=library_hint
    )
    gh_chunks: list[dict] = []
    gh_page_count = 0
    if gh_pages:
        page_chunk_results = await asyncio.gather(
            *[_process_page(page) for page in gh_pages]
        )
        for page_chunks in page_chunk_results:
            gh_chunks.extend(page_chunks)
        gh_page_count = len(gh_pages)

        # Quality gate: if GitHub raw produced too few meaningful chunks,
        # fall through to Tier 2 (crawl docs site). This handles repos
        # where docs use template macros (Polars), RST, or other formats
        # that produce poor raw markdown.
        if len(gh_chunks) >= _MIN_GH_CHUNKS:
            logger.info(
                f"Indexed {len(gh_chunks)} chunks from {len(gh_pages)} "
                "GitHub raw markdown files"
            )
            return gh_chunks, len(gh_pages)
        else:
            logger.info(
                f"GitHub raw produced only {len(gh_chunks)} chunks "
                f"(min {_MIN_GH_CHUNKS}), falling through to crawl"
            )

    # Tier 2: Crawl docs pages (rendered HTML -> markdown)
    pages = await fetch_docs_pages(
        docs_url=docs_url,
        query=query,
        max_pages=50,
    )
    chunks: list[dict] = []
    if pages:
        page_chunk_results = await asyncio.gather(
            *[_process_page(page) for page in pages]
        )
        for page_chunks in page_chunk_results:
            chunks.extend(page_chunks)

    # If Tier 2 crawl produced no results (e.g. Cloudflare blocked) but
    # Tier 1 GitHub raw had some content (below threshold), use it instead
    # of returning nothing.  Some docs are better than no docs.
    if not chunks and gh_chunks:
        logger.info(
            f"Crawl produced 0 chunks, using {len(gh_chunks)} GitHub raw "
            f"chunks from {gh_page_count} files (below threshold but "
            "better than nothing)"
        )
        return gh_chunks, gh_page_count

    # Tier 3: Last-resort README fallback.
    # When all tiers fail AND we have a GitHub repo, fetch just the
    # README.md.  This handles repos without a docs/ directory whose
    # docs site is also uncrawlable (Cloudflare, JS-rendered, etc.).
    if not chunks:
        from wet_mcp.sources.docs import _fetch_github_readme

        readme_chunks = await _fetch_github_readme(repo_url or docs_url)
        if readme_chunks:
            logger.info(
                f"All tiers failed, using {len(readme_chunks)} chunks "
                "from GitHub README (last resort)"
            )
            return readme_chunks, 1

    logger.info(f"Indexed {len(chunks)} chunks from {len(pages)} pages")
    return chunks, len(pages)


# ---------------------------------------------------------------------------
# Docs search (library documentation with auto-indexing)
# ---------------------------------------------------------------------------


async def _background_index_and_search(
    library: str,
    lib_key: str,
    language: str | None,
    docs_url: str,
    repo_url: str,
    query: str,
    version: str | None,
    lib_id: str,
    ver_id: str,
):
    """Background task to fetch, chunk, embed, and store docs."""
    try:
        from urllib.parse import urlparse

        from wet_mcp.sources.docs import _normalize_docs_url

        docs_url = _normalize_docs_url(docs_url)
        logger.info(f"Background indexing started for '{library}' from {docs_url}...")

        try:
            all_chunks, page_count = await asyncio.wait_for(
                _fetch_and_chunk_docs(
                    docs_url=docs_url,
                    repo_url=repo_url,
                    query=query,
                    library_hint=library,
                ),
                timeout=_FETCH_TIMEOUT,
            )
        except TimeoutError:
            logger.warning(
                f"Docs fetch timed out after {_FETCH_TIMEOUT}s for '{library}'"
            )
            all_chunks, page_count = [], 0

        # Fallback SearXNG
        if page_count <= 2 and len(all_chunks) < 100:
            fallback_query = (
                f"{library} {language} documentation"
                if language
                else f"{library} documentation"
            )
            try:
                searxng_url = await asyncio.wait_for(
                    ensure_searxng(), timeout=_SEARXNG_TIMEOUT
                )
                fallback_result = await asyncio.wait_for(
                    searxng_search(
                        searxng_url=searxng_url,
                        query=fallback_query,
                        categories="general",
                        max_results=3,
                    ),
                    timeout=15,
                )
                import json

                fallback_data = json.loads(fallback_result)
                tasks = []
                alt_urls = []
                for fr in fallback_data.get("results", []):
                    alt_url = fr.get("url", "")
                    if not alt_url or not alt_url.startswith("http"):
                        continue
                    alt_parsed = urlparse(alt_url)
                    orig_parsed = urlparse(docs_url)
                    if alt_parsed.netloc == orig_parsed.netloc:
                        continue
                    alt_urls.append(alt_url)
                    tasks.append(
                        asyncio.wait_for(
                            _fetch_and_chunk_docs(alt_url, "", query),
                            timeout=_FALLBACK_TIMEOUT,
                        )
                    )

                if tasks:
                    results = await asyncio.gather(*tasks, return_exceptions=True)
                    for i, res in enumerate(results):
                        if isinstance(res, BaseException):
                            continue
                        alt_chunks, alt_pages = res
                        if alt_pages > page_count and len(alt_chunks) > len(all_chunks):
                            docs_url = alt_urls[i]
                            all_chunks = alt_chunks
                            page_count = alt_pages
                            break
            except Exception as e:
                logger.debug(f"SearXNG fallback failed: {e}")

        if not all_chunks:
            logger.error(
                f"Background indexing failed: Could not extract content from {docs_url}"
            )
            return

        # Generate embeddings
        embeddings = None
        if all_chunks:
            from wet_mcp.embedder import get_backend

            if get_backend() is not None:
                embed_texts_list = []
                for c in all_chunks:
                    parts = []
                    if c.get("title"):
                        parts.append(c["title"])
                    if c.get("heading_path") and c.get("heading_path") != c.get(
                        "title"
                    ):
                        parts.append(c["heading_path"])
                    parts.append(c["content"])
                    embed_texts_list.append(" | ".join(parts)[:2000])
                try:
                    embeddings = await asyncio.wait_for(
                        _embed_batch(embed_texts_list), timeout=_EMBED_TIMEOUT
                    )
                except TimeoutError:
                    embeddings = None

        # Store chunks
        _docs_db.add_chunks(
            version_id=ver_id,
            library_id=lib_id,
            chunks=all_chunks,
            embeddings=embeddings,
        )
        _docs_db.mark_version_indexed(ver_id, page_count, len(all_chunks))
        logger.info(
            f"Background indexing complete for '{library}'. Pages: {page_count}, Chunks: {len(all_chunks)}"
        )

    except Exception as e:
        logger.error(f"Background indexing failed for {library}: {e}")


async def _search_cached_index(
    lib_key: str,
    query: str,
    version: str | None,
    limit: int,
) -> str | None:
    """Search an already-indexed library and return JSON results.

    Returns a JSON string with cached search results if the library is
    indexed and has matching chunks, or None if the library needs
    (re-)indexing.
    """
    from wet_mcp.sources.docs import DISCOVERY_VERSION

    lib = _docs_db.get_library(lib_key)

    if lib:
        # Invalidate cache if discovery scoring has been updated
        cached_version = lib.get("discovery_version", 0)
        if cached_version < DISCOVERY_VERSION:
            logger.info(
                f"Library '{lib_key}' cached with discovery v{cached_version} "
                f"(current v{DISCOVERY_VERSION}), forcing re-index"
            )
            lib = None  # Force re-discovery below

    if not lib:
        return None

    # Check if we have indexed chunks
    ver = _docs_db.get_best_version(lib["id"], version)
    if not ver or ver.get("chunk_count", 0) <= 0:
        return None

    # Search existing index — retrieve extra candidates for reranking
    query_embedding = await _embed(query, is_query=True)
    retrieve_limit = limit * _RERANK_CANDIDATE_MULTIPLIER

    results = _docs_db.search(
        query=query,
        library_name=lib_key,
        version=version,
        limit=retrieve_limit,
        query_embedding=query_embedding,
    )

    if not results:
        return None

    # HyDE augmentation: if initial results are poor, try hypothetical doc
    from wet_mcp.sources.search_strategies import (
        _HYDE_SCORE_THRESHOLD,
        generate_hyde_query,
    )

    scores = [r.get("score", 0) for r in results]
    if len(results) < 3 or (scores and max(scores) < _HYDE_SCORE_THRESHOLD):
        library_name = lib_key.split(":")[0]
        hyde_text = await generate_hyde_query(query, library_name)
        if hyde_text:
            hyde_embedding = await _embed(hyde_text, is_query=False)
            hyde_results = _docs_db.search(
                query=query,
                library_name=lib_key,
                version=version,
                limit=retrieve_limit,
                query_embedding=hyde_embedding,
            )
            if hyde_results:
                hyde_scores = [r.get("score", 0) for r in hyde_results]
                # Use HyDE results if they have better top score
                if max(hyde_scores, default=0) > max(scores, default=0):
                    results = hyde_results

    # Extract original library name (strip language suffix for display)
    library = lib_key.split(":")[0]

    # Rerank if available, otherwise truncate to limit
    results = await _rerank_results(query, results, limit)
    return json.dumps(
        {
            "library": library,
            "version": ver.get("version", "latest"),
            "results": results,
            "total": len(results),
            "source": "cached_index",
        },
        ensure_ascii=False,
        indent=2,
    )


async def _discover_docs_url(
    library: str,
    language: str | None,
) -> tuple[str, str, str, str]:
    """Auto-discover documentation URL for a library.

    Tries registry discovery first, then falls back to SearXNG web search.

    Returns:
        Tuple of (docs_url, repo_url, registry, description). Any field
        may be an empty string if discovery failed.
    """
    from wet_mcp.sources.docs import (
        discover_library,
    )

    docs_url = ""
    repo_url = ""
    registry = ""
    description = ""

    # Discover library metadata from registries (with sub-timeout)
    try:
        discovery = await asyncio.wait_for(
            discover_library(library, language=language),
            timeout=_DISCOVERY_TIMEOUT,
        )
    except TimeoutError:
        logger.warning(
            f"Discovery timed out after {_DISCOVERY_TIMEOUT}s for '{library}'"
        )
        discovery = None

    if discovery:
        docs_url = discovery.get("homepage", "")
        repo_url = discovery.get("repository", "")
        registry = discovery.get("registry", "")
        description = discovery.get("description", "")
    else:
        # Fallback: use SearXNG to find docs
        # Include language context for better results
        search_query = (
            f"{library} {language} documentation"
            if language
            else f"{library} official documentation"
        )
        logger.info(f"Registry lookup failed, trying SearXNG for '{library}'...")
        try:
            searxng_url = await asyncio.wait_for(
                ensure_searxng(), timeout=_SEARXNG_TIMEOUT
            )
            search_result = await asyncio.wait_for(
                searxng_search(
                    searxng_url=searxng_url,
                    query=search_query,
                    categories="general",
                    max_results=3,
                ),
                timeout=15,
            )
            search_data = json.loads(search_result)
            top_results = search_data.get("results", [])
            if top_results:
                docs_url = top_results[0].get("url", "")
        except TimeoutError:
            logger.warning("SearXNG discovery fallback timed out")
        except json.JSONDecodeError:
            pass

    return docs_url, repo_url, registry, description


async def _do_docs_search(
    library: str,
    query: str,
    language: str | None = None,
    version: str | None = None,
    limit: int = 10,
) -> str:
    """Search library documentation. Auto-discovers and indexes if needed."""
    if not _docs_db:
        return "Error: Docs database not initialized"

    # Build library identity — include language for DB disambiguation
    # e.g., "redis" (no lang) vs "redis:python" vs "redis:javascript"
    lib_key = f"{library}:{language.lower()}" if language else library

    # Step 1: Check if library is already indexed
    cached = await _search_cached_index(lib_key, query, version, limit)
    if cached:
        return cached

    # Step 2: Auto-discover and index
    logger.info(f"Library '{lib_key}' not indexed, discovering docs...")

    docs_url, repo_url, registry, description = await _discover_docs_url(
        library, language
    )

    if not docs_url:
        # When no docs URL found but we have a GitHub repo URL,
        # use it as the docs source — _fetch_and_chunk_docs will
        # try GitHub raw docs (Tier 1) which often has good docs/.
        if repo_url and "github.com" in repo_url:
            docs_url = repo_url
            logger.info(f"No docs URL for '{library}', using GitHub repo: {repo_url}")
        else:
            return json.dumps(
                {
                    "error": f"Could not find documentation URL for '{library}'",
                    "hint": "Try providing the docs URL directly via extract action",
                },
                ensure_ascii=False,
            )

    # Apply version to docs URL if applicable (e.g. ReadTheDocs, docs.rs)
    from wet_mcp.sources.docs import _apply_version_to_url

    docs_url = _apply_version_to_url(docs_url, version)

    # Create/update library record
    lib_id = _docs_db.upsert_library(
        name=lib_key,
        docs_url=docs_url,
        registry=registry,
        description=description,
    )
    ver_id = _docs_db.upsert_version(
        library_id=lib_id,
        version=version or "latest",
        docs_url=docs_url,
    )

    # Clear old chunks for re-indexing
    _docs_db.clear_version_chunks(ver_id)

    # Step 3: Launch background indexer
    asyncio.create_task(
        _background_index_and_search(
            library=library,
            lib_key=lib_key,
            language=language,
            docs_url=docs_url,
            repo_url=repo_url,
            query=query,
            version=version,
            lib_id=lib_id,
            ver_id=ver_id,
        )
    )

    fallback_data = await _do_immediate_fallback_search(
        docs_url=docs_url,
        library=library,
        language=language,
        query=query,
        limit=limit,
    )

    return json.dumps(
        {
            "status": "indexing_in_progress",
            "message": f"Library '{library}' is currently being downloaded and indexed in the background (this may take 3-5 minutes). In the meantime, here are temporary web search results.",
            "temporary_results": fallback_data.get("results", []),
            "library": library,
            "docs_url": docs_url,
        },
        ensure_ascii=False,
        indent=2,
    )


async def _do_immediate_fallback_search(
    docs_url: str,
    library: str,
    language: str | None,
    query: str,
    limit: int,
) -> dict:
    """Perform an immediate fallback web search while docs are indexing."""
    fallback_search_query = (
        f"site:{urlparse(docs_url).netloc} {query}"
        if docs_url
        else f"{library} {language} {query}"
    )
    fallback_data = {"results": []}
    try:
        searxng_url = await asyncio.wait_for(ensure_searxng(), timeout=_SEARXNG_TIMEOUT)
        fallback_result = await asyncio.wait_for(
            searxng_search(
                searxng_url=searxng_url,
                query=fallback_search_query,
                categories="general",
                max_results=limit,
            ),
            timeout=15,
        )
        fallback_data = json.loads(fallback_result)
        if "results" in fallback_data and fallback_data["results"]:
            fallback_data["results"] = await _rerank_results(
                query, fallback_data["results"], top_n=limit
            )
    except Exception as e:
        logger.debug(f"Immediate fallback search failed: {e}")
    return fallback_data


async def _per_request_sub_scope(
    claims: dict,
    next_,
) -> None:
    """auth_scope middleware: pin the current request's JWT ``sub`` to
    a contextvar so per-tool-call handlers can resolve per-user creds.

    Invoked by mcp-core's BearerMCPApp AFTER JWT verification, BEFORE the
    inner ASGI MCP handler runs. The ``next_()`` coroutine dispatches the
    actual MCP request inside the same asyncio task, so the contextvar
    set here is visible to ``_require_credentials`` and friends, and is
    reset on the way out so a stale sub does not leak between requests
    (a critical guarantee for multi-user safety).
    """
    from wet_mcp.credential_state import _current_sub

    token = _current_sub.set(claims.get("sub"))
    try:
        await next_()
    finally:
        _current_sub.reset(token)


async def run_http_server(port: int = 0) -> None:
    """Run wet-mcp as HTTP server. Local single-user (default) or remote
    multi-user (when ``PUBLIC_URL`` env set).

    Local mode binds 127.0.0.1 with a single shared ``config.enc``. Remote
    multi-user mode binds 0.0.0.0:8080, requires ``MCP_DCR_SERVER_SECRET``
    as proof of intentional multi-user deployment, and scopes credentials
    per JWT ``sub`` (see ``credential_state.store_for_sub`` and the
    :func:`_per_request_sub_scope` ``auth_scope`` middleware).
    """
    from mcp_core.transport.local_server import run_http_server as _run_http

    from wet_mcp.credential_state import save_credentials, wire_gdrive_callbacks
    from wet_mcp.relay_schema import RELAY_SCHEMA

    public_url = os.environ.get("PUBLIC_URL")
    if public_url:
        if not os.environ.get("MCP_DCR_SERVER_SECRET"):
            raise SystemExit(
                "wet-mcp refuses to start: PUBLIC_URL set but "
                "MCP_DCR_SERVER_SECRET missing. Multi-user remote mode "
                "requires the DCR secret as proof of intentional multi-user "
                "deployment (prevents accidental single-user credential leak)."
            )
        host = "0.0.0.0"
        port = int(os.environ.get("MCP_PORT", "8080"))
    else:
        host = "127.0.0.1"

    # MCP_AUTH_DISABLE=1 skips Bearer JWT verification on /mcp -- for
    # deployments behind an external auth boundary (reverse proxy / API
    # gateway). See mcp-core BearerMCPApp.auth_disabled (>=1.15.0-beta.3).
    auth_disabled = os.environ.get("MCP_AUTH_DISABLE") == "1"

    # Only attach the per-request sub scope when running in multi-user
    # remote mode (PUBLIC_URL set). Single-user / local HTTP keeps the
    # legacy env-driven credential path so existing single-user setups
    # are not perturbed.
    auth_scope = _per_request_sub_scope if public_url else None

    await _run_http(
        mcp,  # ty: ignore[invalid-argument-type]
        server_name="wet-mcp",
        relay_schema=RELAY_SCHEMA,
        host=host,
        port=port,
        on_credentials_saved=save_credentials,
        # 2-arg hook: receive BOTH mark_setup_complete and mark_setup_failed
        # so GDrive device code failures (Google invalid_grant / expired /
        # denied) propagate to the browser form instead of leaving it
        # stuck on "Waiting for authorization..." forever.
        setup_complete_hook=wire_gdrive_callbacks,
        auth_scope=auth_scope,
        auth_disabled=auth_disabled,
    )


def main() -> None:
    """Entry point: stdio by default, ``--http`` (or env) opts into HTTP.

    Stdio mode (default): runs FastMCP over stdin/stdout for direct MCP
    client integration (Claude Code, Cursor, VS Code Copilot, ...).
    Stdio reads credentials from env vars only; wet-mcp's basic SearXNG
    search works with zero env, while tools that require upstream API
    keys (e.g. Google Drive sync) return a helpful error if their env
    vars are missing -- no boot-time exit.

    HTTP mode: opt-in via ``--http`` flag, ``MCP_TRANSPORT=http``, or
    ``TRANSPORT_MODE=http``. HTTP is always multi-user-capable: setting
    ``PUBLIC_URL`` (with ``MCP_DCR_SERVER_SECRET`` for proof of intent)
    binds 0.0.0.0:8080 and scopes credentials per JWT ``sub``;
    otherwise it binds 127.0.0.1 for single-user local browser setup.

    See ``~/projects/.superpower/mcp-core/specs/2026-05-01-stdio-pure-http-multiuser.md``.
    """
    http_requested = (
        "--http" in sys.argv
        or os.environ.get("MCP_TRANSPORT") == "http"
        or os.environ.get("TRANSPORT_MODE") == "http"
    )

    if http_requested:
        asyncio.run(run_http_server())
        return

    # Default: stdio. No bridge layer, no daemon discovery.
    mcp.run(transport="stdio")


if __name__ == "__main__":  # pragma: no cover
    main()
