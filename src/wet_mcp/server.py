"""WET MCP Server - Main server definition."""

import asyncio
import functools
import json
import os
import sys
from contextlib import asynccontextmanager
from importlib.resources import files
from urllib.parse import urlparse

from loguru import logger
from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from wet_mcp.cache import WebCache
from wet_mcp.config import settings
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

# Embedding models to try during LiteLLM auto-detection (in priority order).
# Validated against API keys -- first success wins.
_EMBEDDING_CANDIDATES = [
    "gemini/gemini-embedding-001",
    "text-embedding-3-large",
    "embed-multilingual-v3.0",
]

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


@asynccontextmanager
async def _lifespan(_server: FastMCP):
    """Server lifespan: startup SearXNG, init cache/docs DB, cleanup on shutdown."""
    global _web_cache, _docs_db, _embedding_dims

    logger.info("Starting WET MCP Server...")

    # 1. Setup API keys (+ aliases like GOOGLE_API_KEY -> GEMINI_API_KEY)
    from wet_mcp.config import settings

    keys = settings.setup_api_keys()
    if keys:
        logger.info(f"API keys configured: {', '.join(keys.keys())}")

    # Warn about GitHub token for library docs discovery
    if not (os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")):
        logger.warning(
            "No GITHUB_TOKEN set. Library docs discovery will use unauthenticated "
            "GitHub API (60 req/hr limit). Set GITHUB_TOKEN for 5000 req/hr."
        )

    # SearXNG is pre-warmed eagerly as a background task to eliminate
    # startup latency on the first search call. If this instance finds an
    # existing healthy SearXNG (started by another MCP server instance), it
    # reuses it instead of spawning a new subprocess.
    _searxng_warmup_task: asyncio.Task | None = None
    if settings.wet_auto_searxng:
        _searxng_warmup_task = asyncio.create_task(_warmup_searxng())

    # 2. Initialize web cache
    if settings.wet_cache:
        cache_path = settings.get_cache_db_path()
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        _web_cache = WebCache(cache_path)
        logger.info("Web cache enabled")

    # 3. Initialize embedding backend (dual-backend: litellm or local)
    _embedding_dims = settings.resolve_embedding_dims()
    if _embedding_dims == 0:
        _embedding_dims = _DEFAULT_EMBEDDING_DIMS

    async def _init_backends_task():
        try:
            await _init_embedding_backend(keys)
            await _init_reranker_backend()
        except Exception as e:
            logger.error(f"Background backend init failed: {e}")

    asyncio.create_task(_init_backends_task())

    # 5. Initialize docs DB
    docs_path = settings.get_db_path()
    docs_path.parent.mkdir(parents=True, exist_ok=True)
    _docs_db = DocsDB(docs_path, embedding_dims=_embedding_dims)

    # Start auto-sync if configured
    if settings.sync_enabled:
        from wet_mcp.sync import start_auto_sync

        start_auto_sync(_docs_db)

    yield

    logger.info("Shutting down WET MCP Server...")

    # Cancel SearXNG warmup task if still running
    if _searxng_warmup_task and not _searxng_warmup_task.done():
        _searxng_warmup_task.cancel()
        try:
            await _searxng_warmup_task
        except (asyncio.CancelledError, Exception):
            pass

    # Stop auto-sync
    if settings.sync_enabled:
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


async def _init_embedding_backend(keys: dict) -> None:
    """Initialize the embedding backend based on config.

    Always initializes a backend (never FTS5-only):
    - litellm: try cloud model, fallback to local on failure
    - local: always available (GGUF if GPU + llama-cpp, else ONNX)
    """
    global _embedding_dims
    from wet_mcp.embedder import init_backend

    backend_type = settings.resolve_embedding_backend()

    if backend_type == "litellm":
        model = settings.resolve_embedding_model()
        if model:
            # Explicit model -- validate it
            try:
                backend = await asyncio.to_thread(init_backend, "litellm", model)
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
        elif keys:
            # Auto-detect: try candidate models
            for candidate in _EMBEDDING_CANDIDATES:
                try:
                    backend = await asyncio.to_thread(
                        init_backend, "litellm", candidate
                    )
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
        # Cloud not available -- fallback to local
        logger.warning("Cloud embedding not available, using local fallback")

    # Local backend (always available)
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


async def _init_reranker_backend() -> None:
    """Initialize the reranker backend based on config.

    Always initializes a backend unless reranking is disabled:
    - litellm: use RERANK_MODEL or auto-detected from API_KEYS (Cohere)
    - local: always available (GGUF if GPU + llama-cpp, else ONNX)
    """
    rerank_backend_type = settings.resolve_rerank_backend()

    if not rerank_backend_type:
        logger.info("Reranking disabled")
        return

    from wet_mcp.reranker import init_reranker

    if rerank_backend_type == "litellm":
        model = settings.resolve_rerank_model()
        if model:
            try:
                reranker = await asyncio.to_thread(init_reranker, "litellm", model)
                available = await asyncio.to_thread(reranker.check_available)
                if available:
                    logger.info(f"Reranker: {model} (cloud)")
                    return
            except Exception as e:
                logger.warning(f"Cloud reranker {model} not available: {e}")
        # Cloud not available -- fallback to local
        logger.warning("Cloud reranking not available, using local fallback")

    # Local backend (always available)
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
        "Use `search` for web/academic/docs search. "
        "Use `extract` for content extraction, crawling, site mapping. "
        "Use `media` for media discovery and download. "
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
async def search(
    action: str,
    query: str | None = None,
    library: str | None = None,
    version: str | None = None,
    language: str | None = None,
    categories: str = "general",
    max_results: int = 10,
    limit: int = 10,
) -> str:
    """Search the web, academic papers, or library documentation.
    - search: Web search via SearXNG (requires query)
    - research: Academic/scientific search (requires query)
    - docs: Search library documentation with auto-indexing (requires library + query, specify language for disambiguation)
    Use `help` tool for full documentation.
    """
    match action:
        case "search":
            if not query:
                return "Error: query is required for search action"
            cache_params = {
                "query": query,
                "categories": categories,
                "max_results": max_results,
            }
            if _web_cache:
                cached = _web_cache.get("search", cache_params)
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
            result = await _with_timeout(
                searxng_search(
                    searxng_url=searxng_url,
                    query=query,
                    categories=categories,
                    max_results=max_results,
                ),
                "search",
            )
            if _web_cache and not result.startswith("Error"):
                _web_cache.set("search", cache_params, result)
            return result

        case "research":
            if not query:
                return "Error: query is required for research action"
            cache_params = {"query": query, "max_results": max_results}
            if _web_cache:
                cached = _web_cache.get("research", cache_params)
                if cached:
                    return cached
            result = await _with_timeout(
                _do_research(query=query, max_results=max_results),
                "research",
            )
            if _web_cache and not result.startswith("Error"):
                _web_cache.set("research", cache_params, result)
            return result

        case "docs":
            if not library:
                return "Error: library is required for docs action"
            if not query:
                return "Error: query is required for docs action"
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

        case _:
            return (
                f"Error: Unknown action '{action}'. "
                "Valid actions: search, research, docs"
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
    depth: int = 2,
    max_pages: int = 20,
    format: str = "markdown",
    stealth: bool = False,
) -> str:
    """Extract content from web pages, crawl sites, or map site structure.
    - extract: Get clean content from URLs (requires urls)
    - crawl: Deep crawl from root URLs (requires urls)
    - map: Discover site structure without content (requires urls)
    Use `help` tool for full documentation.
    """
    match action:
        case "extract":
            if not urls:
                return "Error: urls is required for extract action"
            cache_params = {"urls": sorted(urls), "format": format, "stealth": stealth}
            if _web_cache:
                cached = _web_cache.get("extract", cache_params)
                if cached:
                    return cached
            result = await _with_timeout(
                _extract(urls=urls, format=format, stealth=stealth),
                "extract",
            )
            if _web_cache and not result.startswith("Error"):
                _web_cache.set("extract", cache_params, result)
            return result

        case "crawl":
            if not urls:
                return "Error: urls is required for crawl action"
            cache_params = {
                "urls": sorted(urls),
                "depth": depth,
                "max_pages": max_pages,
            }
            if _web_cache:
                cached = _web_cache.get("crawl", cache_params)
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
                _web_cache.set("crawl", cache_params, result)
            return result

        case "map":
            if not urls:
                return "Error: urls is required for map action"
            cache_params = {
                "urls": sorted(urls),
                "depth": depth,
                "max_pages": max_pages,
            }
            if _web_cache:
                cached = _web_cache.get("map", cache_params)
                if cached:
                    return cached
            result = await _with_timeout(
                _sitemap(urls=urls, depth=depth, max_pages=max_pages),
                "map",
            )
            if _web_cache and not result.startswith("Error"):
                _web_cache.set("map", cache_params, result)
            return result

        case _:
            return (
                f"Error: Unknown action '{action}'. Valid actions: extract, crawl, map"
            )


@mcp.tool(
    annotations=ToolAnnotations(
        readOnlyHint=False,
        openWorldHint=True,
    ),
)
@_wrap_tool("media")
async def media(
    action: str,
    url: str | None = None,
    media_type: str = "all",
    media_urls: list[str] | None = None,
    output_dir: str | None = None,
    max_items: int = 10,
    prompt: str = "Describe this image in detail.",
) -> str:
    """Media discovery and download.
    - list: Scan page, return URLs + metadata
    - download: Download specific files to local
    - analyze: Analyze a local media file using configured LLM (requires API_KEYS)

    Note: Downloading is intended for downstream analysis (e.g., passing to an LLM
    or vision model). The MCP server provides the raw files; the MCP client
    orchestrates the analysis.

    Use `help` tool for full documentation.
    """
    from wet_mcp.sources.crawler import download_media

    match action:
        case "list":
            if not url:
                return "Error: url is required for list action"
            return await _with_timeout(
                list_media(url=url, media_type=media_type, max_items=max_items),
                "media.list",
            )

        case "download":
            if not media_urls:
                return "Error: media_urls is required for download action"
            return await _with_timeout(
                download_media(
                    media_urls=media_urls,
                    output_dir=output_dir or settings.download_dir,
                ),
                "media.download",
            )

        case "analyze":
            if not url:
                return "Error: url (local path) is required for analyze action"

            from wet_mcp.llm import analyze_media

            return await _with_timeout(
                analyze_media(media_path=url, prompt=prompt),
                "media.analyze",
            )

        case _:
            return f"Error: Unknown action '{action}'. Valid actions: list, download, analyze"


@mcp.tool(
    annotations=ToolAnnotations(
        readOnlyHint=True,
        openWorldHint=False,
        idempotentHint=True,
    ),
)
async def help(tool_name: str = "search") -> str:
    """Get full documentation for a tool.
    Use when compressed descriptions are insufficient.
    Valid tool names: search, extract, media, config, help.
    """
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
        "status|set|cache_clear|docs_reindex. "
        "Use help tool with tool_name='config' for full docs."
    ),
    annotations=ToolAnnotations(
        title="Config",
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    ),
)
async def config(
    action: str,
    key: str | None = None,
    value: str | None = None,
) -> str:
    """Server configuration and management.

    Actions:
    - status: Show current config and status
    - set: Update runtime setting (key + value required)
    - cache_clear: Clear web cache
    - docs_reindex: Force re-index a library (key = library name)
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
                    "remote": settings.sync_remote,
                    "folder": settings.sync_folder,
                    "interval": settings.sync_interval,
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
                "sync_remote",
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
            elif key == "tool_timeout":
                settings.tool_timeout = int(value)
            elif key == "wet_cache":
                settings.wet_cache = value.lower() in (
                    "true",
                    "1",
                    "yes",
                )
            elif key == "sync_enabled":
                settings.sync_enabled = value.lower() in (
                    "true",
                    "1",
                    "yes",
                )
            elif key == "sync_interval":
                settings.sync_interval = int(value)
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
                _web_cache.clear()
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
            return json.dumps(
                {
                    "error": f"Unknown action: {action}",
                    "valid_actions": [
                        "status",
                        "set",
                        "cache_clear",
                        "docs_reindex",
                    ],
                }
            )


# ---------------------------------------------------------------------------
# Research (academic search via SearXNG science category)
# ---------------------------------------------------------------------------


async def _do_research(query: str, max_results: int = 10) -> str:
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
        max_results=max_results,
    )

    # Re-format results for academic context
    try:
        data = json.loads(result_str)
        results = data.get("results", [])

        # Enrich with academic metadata hints
        for r in results:
            url = r.get("url", "")
            if "arxiv.org" in url:
                r["source_type"] = "arxiv"
            elif "scholar.google" in url:
                r["source_type"] = "google_scholar"
            elif "semanticscholar.org" in url:
                r["source_type"] = "semantic_scholar"
            elif "pubmed" in url or "nih.gov" in url:
                r["source_type"] = "pubmed"
            elif "doi.org" in url:
                r["source_type"] = "doi"
            else:
                r["source_type"] = "academic"

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
            page_chunks = chunk_markdown(
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
        page_chunks = chunk_markdown(
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

    from wet_mcp.sources.docs import DISCOVERY_VERSION

    # Step 1: Check if library is already indexed
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

    if lib:
        # Check if we have indexed chunks
        ver = _docs_db.get_best_version(lib["id"], version)
        if ver and ver.get("chunk_count", 0) > 0:
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

            if results:
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

    # Step 2: Auto-discover and index
    logger.info(f"Library '{lib_key}' not indexed, discovering docs...")

    from wet_mcp.sources.docs import (
        discover_library,
    )

    # Discover library metadata from registries (with sub-timeout)
    docs_url = ""
    repo_url = ""
    registry = ""
    description = ""
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

    # Step 3: Fetch and chunk docs (tiered: llms.txt > GitHub raw > crawl)
    # Normalize docs URL (strip overly-specific paths for better crawl coverage)
    from wet_mcp.sources.docs import _normalize_docs_url

    docs_url = _normalize_docs_url(docs_url)

    logger.info(f"Fetching docs for '{library}' from {docs_url}...")
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
        logger.warning(f"Docs fetch timed out after {_FETCH_TIMEOUT}s for '{library}'")
        all_chunks, page_count = [], 0

    # Fallback: if too few pages (likely wrong/insufficient docs URL),
    # try SearXNG to discover a better documentation URL.
    if page_count <= 2 and len(all_chunks) < 100:
        fallback_query = (
            f"{library} {language} documentation"
            if language
            else f"{library} documentation"
        )
        logger.info(
            f"Only {page_count} pages found for '{library}', trying SearXNG fallback..."
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
            fallback_data = json.loads(fallback_result)
            for fr in fallback_data.get("results", []):
                alt_url = fr.get("url", "")
                if not alt_url or not alt_url.startswith("http"):
                    continue
                alt_parsed = urlparse(alt_url)
                orig_parsed = urlparse(docs_url)
                if alt_parsed.netloc == orig_parsed.netloc:
                    continue
                try:
                    alt_chunks, alt_pages = await asyncio.wait_for(
                        _fetch_and_chunk_docs(alt_url, "", query),
                        timeout=_FALLBACK_TIMEOUT,
                    )
                except TimeoutError:
                    logger.warning(f"SearXNG fallback fetch timed out for {alt_url}")
                    continue
                if alt_pages > page_count and len(alt_chunks) > len(all_chunks):
                    logger.info(
                        f"SearXNG fallback: {alt_url} "
                        f"({alt_pages} pages, {len(alt_chunks)} chunks)"
                    )
                    docs_url = alt_url
                    all_chunks = alt_chunks
                    page_count = alt_pages
                    break
        except TimeoutError:
            logger.warning("SearXNG fallback timed out")
        except Exception as e:
            logger.debug(f"SearXNG fallback failed: {e}")

    if not all_chunks:
        return json.dumps(
            {
                "error": f"Could not extract documentation content from {docs_url}",
                "docs_url": docs_url,
            },
            ensure_ascii=False,
        )

    # Step 4: Generate embeddings (optional, with sub-timeout)
    embeddings = None
    if all_chunks:
        from wet_mcp.embedder import get_backend

        if get_backend() is not None:
            # Build embedding text: prepend title + heading for context, then content
            # Truncate to 2000 chars to balance quality vs cost
            embed_texts_list = []
            for c in all_chunks:
                parts = []
                if c.get("title"):
                    parts.append(c["title"])
                if c.get("heading_path") and c.get("heading_path") != c.get("title"):
                    parts.append(c["heading_path"])
                parts.append(c["content"])
                embed_texts_list.append(" | ".join(parts)[:2000])
            logger.info(f"Generating embeddings for {len(embed_texts_list)} chunks...")
            try:
                embeddings = await asyncio.wait_for(
                    _embed_batch(embed_texts_list),
                    timeout=_EMBED_TIMEOUT,
                )
            except TimeoutError:
                logger.warning(
                    f"Embedding timed out after {_EMBED_TIMEOUT}s "
                    f"for {len(embed_texts_list)} chunks, skipping"
                )
                embeddings = None
            if embeddings:
                logger.info(f"Generated {len(embeddings)} embeddings")

    # Step 5: Store chunks
    _docs_db.add_chunks(
        version_id=ver_id,
        library_id=lib_id,
        chunks=all_chunks,
        embeddings=embeddings,
    )
    _docs_db.mark_version_indexed(ver_id, page_count, len(all_chunks))

    # Step 6: Search the freshly indexed content
    query_embedding = await _embed(query, is_query=True)
    retrieve_limit = limit * _RERANK_CANDIDATE_MULTIPLIER

    results = _docs_db.search(
        query=query,
        library_name=lib_key,
        version=version,
        limit=retrieve_limit,
        query_embedding=query_embedding,
    )

    # Rerank if available
    results = await _rerank_results(query, results, limit)

    return json.dumps(
        {
            "library": library,
            "version": version or "latest",
            "docs_url": docs_url,
            "results": results,
            "total": len(results),
            "source": "freshly_indexed",
            "pages_crawled": page_count,
            "chunks_indexed": len(all_chunks),
        },
        ensure_ascii=False,
        indent=2,
    )


# ---------------------------------------------------------------------------
# Prompts (aligned with mnemo-mcp pattern)
# ---------------------------------------------------------------------------


@mcp.prompt()
def research_topic(topic: str) -> str:
    """Generate a prompt to research a topic using academic search."""
    return (
        f"Research the following topic thoroughly: {topic}\n\n"
        "1. Use the search tool with action='research' to find academic papers.\n"
        "2. Use the extract tool with action='extract' on the most relevant URLs.\n"
        "3. Synthesize findings into a comprehensive summary with citations."
    )


@mcp.prompt()
def library_docs(library: str, question: str) -> str:
    """Generate a prompt to find library documentation."""
    return (
        f"Find documentation for '{library}' to answer: {question}\n\n"
        "Use the search tool with action='docs', library='{library}', "
        f"query='{question}'. If results are insufficient, use extract tool "
        "to get more content from the documentation URLs."
    )


def main() -> None:
    """Entry point for the MCP server."""
    mcp.run()


if __name__ == "__main__":
    main()
