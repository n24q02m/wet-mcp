"""WET MCP Server - Main server definition."""

import asyncio
import functools
import json
import os
import sys
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

    When state is AWAITING_SETUP: BLOCK the tool — return error with setup instructions.
    When state is LOCAL: allow (user explicitly chose local mode via skip).
    When state is CONFIGURED: allow.
    """
    from wet_mcp.credential_state import CredentialState, get_setup_url, get_state

    state = get_state()
    if state == CredentialState.AWAITING_SETUP:
        url = get_setup_url()
        return json.dumps(
            {
                "error": "Credentials not configured",
                "state": "awaiting_setup",
                "setup_url": url,
                "instructions": (
                    "API keys required. Call setup(action='open_relay') to configure via browser, "
                    "or setup(action='skip') to opt into local-only mode."
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
    from wet_mcp.credential_state import resolve_credential_state

    resolve_credential_state()

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
    warmup_task: asyncio.Task | None = None
    if settings.wet_auto_searxng:
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

    # 5. Initialize docs DB
    docs_path = settings.get_db_path()
    docs_path.parent.mkdir(parents=True, exist_ok=True)
    _docs_db = DocsDB(docs_path, embedding_dims=_embedding_dims)

    # Start auto-sync when Google Drive client ID is configured
    if settings.google_drive_client_id:
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

    # Stop auto-sync
    from wet_mcp.config import settings

    if settings.google_drive_client_id:
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
            native_dims = await asyncio.to_thread(backend.check_available)
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
            native_dims = await asyncio.to_thread(backend.check_available)
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
                native_dims = await asyncio.to_thread(backend.check_available)
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
            return await asyncio.to_thread(
                backend.embed_single_query, text, _embedding_dims
            )
        return await asyncio.to_thread(backend.embed_single, text, _embedding_dims)
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
        return await asyncio.to_thread(backend.embed_texts, texts, _embedding_dims)
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

    match action:
        case "search":
            if not query:
                return 'Error: query is required for search action. Example: search(action="search", query="python async patterns")'
            cache_params = {
                "query": query,
                "categories": categories,
                "max_results": max_results,
                "time_range": time_range,
                "language": language,
                "include_domains": include_domains,
                "exclude_domains": exclude_domains,
            }
            if _web_cache:
                cached = await asyncio.to_thread(_web_cache.get, "search", cache_params)
                if cached:
                    return cached
            try:
                searxng_url = await asyncio.wait_for(
                    ensure_searxng(), timeout=_SEARXNG_TIMEOUT
                )
            except TimeoutError:
                return f"Error: SearXNG startup timed out ({_SEARXNG_TIMEOUT}s). Try again or check logs."
            except (SystemExit, Exception) as exc:
                return f"Error: SearXNG startup failed: {exc}"
            # Optional query expansion
            search_query = query
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

                    if modified:
                        result = json.dumps(data, ensure_ascii=False, indent=2)
                except json.JSONDecodeError:
                    pass
            if _web_cache and not result.startswith("Error"):
                await asyncio.to_thread(_web_cache.set, "search", cache_params, result)
            if not result.startswith("Error"):
                try:
                    _data = json.loads(result)
                    result = json.dumps(_data, ensure_ascii=False, indent=2)
                except (json.JSONDecodeError, Exception):
                    pass
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
            if not result.startswith("Error"):
                try:
                    _data = json.loads(result)
                    result = json.dumps(_data, ensure_ascii=False, indent=2)
                except (json.JSONDecodeError, Exception):
                    pass
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

        case _:
            import difflib

            valid_actions = ["docs", "research", "search", "similar"]
            closest = difflib.get_close_matches(action, valid_actions, n=1)
            suggestion = f" Did you mean '{closest[0]}'?" if closest else ""
            return (
                f"Error: Unknown action '{action}'.{suggestion} "
                "Valid actions: search (web search), research (academic), docs (library documentation), similar (find related pages). "
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
async def extract(
    action: str,
    urls: list[str] | None = None,
    paths: list[str] | None = None,
    depth: int = 2,
    max_pages: int = 20,
    format: str = "markdown",
    stealth: bool = False,
    schema: dict | None = None,
    prompt: str | None = None,
) -> str:
    """Read and return full page content from URLs or local files. Use this when you have a specific URL and need its content. For finding URLs first, use the `search` tool instead.

    Actions:
    - extract: Get clean content from URLs. Example: extract(action="extract", urls=["https://example.com/article"])
    - batch: Batch extract with per-domain rate limiting (max 50 URLs). Example: extract(action="batch", urls=["https://a.com/1", "https://b.com/2"])
    - crawl: Deep crawl following links from root URLs. Example: extract(action="crawl", urls=["https://docs.example.com"], depth=2)
    - map: Discover site URL structure without extracting content. Example: extract(action="map", urls=["https://example.com"])
    - convert: Convert local files (PDF, DOCX, PPTX, XLSX) to Markdown. Example: extract(action="convert", paths=["/home/user/report.pdf"])
    - extract_structured: Extract structured data using JSON Schema + LLM. Example: extract(action="extract_structured", urls=["https://example.com/pricing"], schema={"type": "object", "properties": {"price": {"type": "string"}}})

    Key parameters:
    - urls (required for extract/batch/crawl/map/extract_structured): List of URLs
    - paths (required for convert): List of local file paths
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
            if not result.startswith("Error"):
                try:
                    _data = json.loads(result)
                    result = json.dumps(_data, ensure_ascii=False, indent=2)
                except (json.JSONDecodeError, Exception):
                    pass
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

        case _:
            import difflib

            valid_actions = [
                "batch",
                "convert",
                "crawl",
                "extract",
                "extract_structured",
                "map",
            ]
            closest = difflib.get_close_matches(action, valid_actions, n=1)
            suggestion = f" Did you mean '{closest[0]}'?" if closest else ""
            return (
                f"Error: Unknown action '{action}'.{suggestion} "
                "Valid actions: extract (read URL content), batch (bulk extract), crawl (follow links), "
                "map (site structure), convert (local files to markdown), extract_structured (schema-based). "
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
    """Discover, download, and analyze media files (images, videos, audio) from web pages.

    Actions:
    - list: Scan a page and return media URLs with metadata. Example: media(action="list", url="https://example.com/gallery", media_type="images")
    - download: Download media files to local storage. Example: media(action="download", media_urls=["https://example.com/photo.jpg"])
    - analyze: Analyze a local file using LLM vision (requires API_KEYS). Example: media(action="analyze", url="/path/to/image.jpg", prompt="What objects are in this image?")

    Key parameters:
    - url (required for list/analyze): Page URL to scan, or local file path for analyze
    - media_urls (required for download): List of media URLs to download
    - media_type: Filter for list -- "images", "videos", "audio", "files", "all" (default: "all")
    - output_dir: Download directory (default: ~/.wet-mcp/downloads)
    - prompt: Analysis prompt for analyze action

    Typical workflow: list (discover) -> download (save locally) -> analyze (LLM insights).
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

        case "analyze":
            if not url:
                return 'Error: url (local file path) is required for analyze action. Example: media(action="analyze", url="/path/to/image.jpg", prompt="Describe this image"). Download a file first with media(action="download", ...).'

            from wet_mcp.llm import analyze_media

            result = await _with_timeout(
                analyze_media(media_path=url, prompt=prompt),
                "media.analyze",
            )
            if not result.startswith("Error"):
                try:
                    _data = json.loads(result)
                    result = json.dumps(_data, ensure_ascii=False, indent=2)
                except (json.JSONDecodeError, Exception):
                    pass
            return result

        case _:
            import difflib

            valid_actions = ["analyze", "download", "list"]
            closest = difflib.get_close_matches(action, valid_actions, n=1)
            suggestion = f" Did you mean '{closest[0]}'?" if closest else ""
            return f"Error: Unknown action '{action}'.{suggestion} Valid actions: list (discover media on page), download (save to local), analyze (LLM vision analysis)."


@mcp.tool(
    annotations=ToolAnnotations(
        readOnlyHint=True,
        openWorldHint=False,
        idempotentHint=True,
    ),
)
async def help(tool_name: str = "search") -> str:
    """Get detailed documentation for any tool. Call this when you need full parameter reference or usage examples.

    Valid tool_name values: search, extract, media, config, help.

    Quick guide -- which tool to use:
    - Need to FIND information? Use `search` (returns result listings with URLs)
    - Need to READ a page? Use `extract` (returns full page content from a URL)
    - Need media files? Use `media` (discover, download, analyze images/videos/audio)
    - Need server settings? Use `config` (status, cache, settings, warmup, sync setup)
    """
    allowed_tools = {"search", "extract", "media", "config", "help"}
    if tool_name not in allowed_tools:
        import difflib

        closest = difflib.get_close_matches(tool_name, sorted(allowed_tools), n=1)
        suggestion = f" Did you mean '{closest[0]}'?" if closest else ""
        return f"Error: Invalid tool_name '{tool_name}'.{suggestion} Valid options: {', '.join(sorted(allowed_tools))}."

    try:
        doc_file = files("wet_mcp.docs").joinpath(f"{tool_name}.md")
        return doc_file.read_text()
    except FileNotFoundError:
        return f"Error: No documentation found for tool '{tool_name}'"
    except Exception as e:
        return f"Error loading documentation: {e}"


@mcp.tool(
    description=(
        "Server config and management. Actions: "
        "status|set|cache_clear|docs_reindex|warmup|setup_sync. "
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
) -> str:
    """Server configuration and management.

    Actions:
    - status: Show current config and status
    - set: Update runtime setting (key + value required)
    - cache_clear: Clear web cache
    - docs_reindex: Force re-index a library (key = library name)
    - warmup: Pre-download models and run first-time setup
    - setup_sync: Configure Google Drive sync (OAuth Device Code flow)
    """
    match action:
        case "status":
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
                    "backend": (
                        type(embed_backend).__name__ if embed_backend else None
                    ),
                    "dims": _embedding_dims,
                    "available": embed_backend is not None,
                },
                "reranker": {
                    "available": reranker is not None,
                    "backend": (type(reranker).__name__ if reranker else None),
                },
                "cache": {
                    "enabled": settings.wet_cache,
                    "path": (
                        str(settings.get_cache_db_path())
                        if settings.wet_cache
                        else None
                    ),
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

        case "set":
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
                return json.dumps(
                    {
                        "error": f"Invalid key: {key}",
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

        case "cache_clear":
            if _web_cache:
                await asyncio.to_thread(_web_cache.clear)
                return json.dumps({"status": "cache cleared"})
            return json.dumps({"error": "Cache is not enabled"})

        case "docs_reindex":
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
                        "hint": ("Next docs search will re-index"),
                    }
                )
            return json.dumps({"error": f"Library '{key}' not found in index"})

        case _:
            import difflib

            valid_actions = ["cache_clear", "docs_reindex", "set", "status"]
            closest = difflib.get_close_matches(action, valid_actions, n=1)
            suggestion = f" Did you mean '{closest[0]}'?" if closest else ""
            return json.dumps(
                {
                    "error": f"Unknown action '{action}'.{suggestion}",
                    "valid_actions": valid_actions,
                }
            )


# ---------------------------------------------------------------------------
# Setup (warmup + setup-sync as MCP tool)
# ---------------------------------------------------------------------------


@mcp.tool(
    description=(
        "Server setup, credentials, and warmup. Actions: "
        "open_relay|status|skip|reset|complete|warmup|setup_sync. "
        "open_relay: Open browser-based setup page to configure all API keys at once. "
        "status: Show current credential state and configured keys. "
        "skip: Use local ONNX models (explicit opt-in, no cloud). "
        "reset: Clear all credentials and reset state. "
        "complete: Re-resolve credentials from environment. "
        "warmup: Pre-download models and install dependencies. "
        "setup_sync: Configure Google Drive sync (OAuth Device Code)."
    ),
    annotations=ToolAnnotations(
        title="Setup",
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=True,
    ),
)
async def setup(
    action: str,
    key: str | None = None,
    value: str | None = None,
    remote_type: str | None = None,
    force: bool = False,
) -> str:
    """Server setup, credentials, and warmup.

    Actions:
    - open_relay: Open browser-based setup to configure all API keys at once.
    - status: Show current credential state and configured keys.
    - skip: Use local ONNX models (explicit opt-in, no cloud features).
    - reset: Clear all credentials and reset state.
    - complete: Re-resolve credentials from environment.
    - warmup: Pre-download models and install dependencies.
    - setup_sync: Configure Google Drive sync (OAuth Device Code).
    """
    from wet_mcp.setup_tool import run_setup_sync, run_warmup

    match action:
        case "open_relay":
            from wet_mcp.credential_state import trigger_relay_setup

            url = await trigger_relay_setup(force=force)
            if url:
                return json.dumps(
                    {
                        "status": "relay_started",
                        "setup_url": url,
                        "message": "Browser opened. Configure API keys in the form, then submit.",
                    }
                )
            return json.dumps(
                {"status": "error", "message": "Failed to start relay session."}
            )

        case "warmup":
            result = await run_warmup()
            return json.dumps(result, indent=2, default=str)

        case "setup_sync":
            result = await run_setup_sync(remote_type or "drive")
            return json.dumps(result, indent=2, default=str)

        case "status":
            from wet_mcp import credential_state as _cs

            state = _cs.get_state()
            return json.dumps(
                {
                    "state": state.value,
                    "setup_url": _cs.get_setup_url(),
                    "cloud_keys_in_env": [
                        k for k in _cs.CLOUD_KEYS if os.environ.get(k)
                    ],
                }
            )

        case "start" | "setup_relay":
            # Backward compat aliases → redirect to open_relay
            from wet_mcp.credential_state import trigger_relay_setup

            url = await trigger_relay_setup(force=force)
            if url:
                return json.dumps({"status": "relay_started", "setup_url": url})
            return json.dumps({"status": "error", "message": "Relay setup failed."})

        case "skip":
            from mcp_relay_core import set_local_mode

            from wet_mcp.credential_state import CredentialState, set_state

            set_local_mode("wet-mcp")
            set_state(CredentialState.LOCAL)
            return json.dumps(
                {
                    "status": "ok",
                    "message": "Local mode set. Relay will not trigger on restart.",
                }
            )

        case "reset":
            from wet_mcp.credential_state import reset_state

            reset_state()
            return json.dumps(
                {
                    "status": "ok",
                    "message": "Credentials cleared. Next tool call will offer setup.",
                }
            )

        case "complete":
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

        case _:
            import difflib

            valid_actions = [
                "complete",
                "open_relay",
                "reset",
                "setup_sync",
                "skip",
                "start",
                "status",
                "warmup",
            ]
            closest = difflib.get_close_matches(action, valid_actions, n=1)
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

    # Tier 1: Try GitHub raw markdown (clean content, no JS rendering)
    gh_target = repo_url or docs_url
    gh_pages = await _try_github_raw_docs(
        gh_target, max_files=50, library_hint=library_hint
    )
    gh_chunks: list[dict] = []
    gh_page_count = 0
    if gh_pages:
        for page in gh_pages:
            page_chunks = await asyncio.to_thread(
                chunk_markdown,
                content=page["content"],
                url=page.get("url", ""),
            )
            for chunk in page_chunks:
                if not chunk.get("title") and page.get("title"):
                    chunk["title"] = page["title"]
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
    for page in pages:
        page_chunks = await asyncio.to_thread(
            chunk_markdown,
            content=page["content"],
            url=page.get("url", ""),
        )
        for chunk in page_chunks:
            if not chunk.get("title") and page.get("title"):
                chunk["title"] = page["title"]
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


def main() -> None:
    """Entry point for the MCP server."""
    mcp.run()


if __name__ == "__main__":  # pragma: no cover
    main()
