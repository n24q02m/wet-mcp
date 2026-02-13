"""WET MCP Server - Main server definition."""

import asyncio
import json
import sys
from contextlib import asynccontextmanager
from importlib.resources import files

from loguru import logger
from mcp.server.fastmcp import FastMCP

from wet_mcp.cache import WebCache
from wet_mcp.config import settings
from wet_mcp.db import DocsDB
from wet_mcp.searxng_runner import ensure_searxng, stop_searxng
from wet_mcp.sources.crawler import (
    crawl as _crawl,
)
from wet_mcp.sources.crawler import (
    extract as _extract,
)
from wet_mcp.sources.crawler import (
    list_media,
)
from wet_mcp.sources.crawler import (
    sitemap as _sitemap,
)
from wet_mcp.sources.searxng import search as searxng_search

# Configure logging
logger.remove()
logger.add(sys.stderr, level=settings.log_level)

# Embedding models to try during auto-detection (in priority order).
# LiteLLM validates each against its API key -- first success wins.
_EMBEDDING_CANDIDATES = [
    "gemini/gemini-embedding-001",
    "text-embedding-3-small",
    "mistral/mistral-embed",
    "embed-english-v3.0",
]

# Fixed embedding dimensions for sqlite-vec.
# All embeddings are truncated to this size so switching models never
# breaks the vector table. Override via EMBEDDING_DIMS env var.
_DEFAULT_EMBEDDING_DIMS = 768

# Module-level state (set during lifespan)
_web_cache: WebCache | None = None
_docs_db: DocsDB | None = None
_embedding_model: str | None = None
_embedding_dims: int = 0


@asynccontextmanager
async def _lifespan(_server: FastMCP):
    """Server lifespan: startup SearXNG, init cache/docs DB, cleanup on shutdown."""
    global _web_cache, _docs_db, _embedding_model, _embedding_dims

    from wet_mcp.setup import run_auto_setup

    logger.info("Starting WET MCP Server...")
    await asyncio.to_thread(run_auto_setup)

    # 1. Setup API keys (+ aliases like GOOGLE_API_KEY -> GEMINI_API_KEY)
    keys = settings.setup_api_keys()
    if keys:
        logger.info(f"API keys configured: {', '.join(keys.keys())}")

    # Pre-import crawl4ai -- its first import runs heavy synchronous init
    # that would block the event loop if deferred to the first tool call.
    logger.info("Pre-loading Crawl4AI...")
    await asyncio.to_thread(__import__, "crawl4ai")
    logger.info("Crawl4AI loaded")

    searxng_url = await ensure_searxng()
    logger.info(f"SearXNG URL: {searxng_url}")

    # 2. Initialize web cache
    if settings.wet_cache:
        cache_path = settings.get_cache_db_path()
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        _web_cache = WebCache(cache_path)
        logger.info("Web cache enabled")

    # 3. Resolve embedding model + dims
    _embedding_model = settings.resolve_embedding_model()
    _embedding_dims = settings.resolve_embedding_dims()

    if _embedding_model:
        # Explicit model -- validate it
        from wet_mcp.embedder import check_embedding_available

        native_dims = await asyncio.to_thread(
            check_embedding_available, _embedding_model
        )
        if native_dims > 0:
            if _embedding_dims == 0:
                _embedding_dims = _DEFAULT_EMBEDDING_DIMS
            logger.info(
                f"Embedding: {_embedding_model} "
                f"(native={native_dims}, stored={_embedding_dims})"
            )
        else:
            logger.warning(
                f"Embedding model {_embedding_model} not available, using FTS5-only"
            )
            _embedding_model = None
    elif keys:
        # Auto-detect: try candidate models
        from wet_mcp.embedder import check_embedding_available

        for candidate in _EMBEDDING_CANDIDATES:
            native_dims = await asyncio.to_thread(check_embedding_available, candidate)
            if native_dims > 0:
                _embedding_model = candidate
                if _embedding_dims == 0:
                    _embedding_dims = _DEFAULT_EMBEDDING_DIMS
                logger.info(
                    f"Embedding: {_embedding_model} "
                    f"(native={native_dims}, stored={_embedding_dims})"
                )
                break
        if not _embedding_model:
            logger.warning("No embedding model available, using FTS5-only")
    else:
        logger.info("No API keys configured, using FTS5-only search")

    # 4. Initialize docs DB
    docs_path = settings.get_db_path()
    docs_path.parent.mkdir(parents=True, exist_ok=True)
    _docs_db = DocsDB(docs_path, embedding_dims=_embedding_dims)

    # Start auto-sync if configured
    if settings.sync_enabled:
        from wet_mcp.sync import start_auto_sync

        start_auto_sync(_docs_db)

    yield

    logger.info("Shutting down WET MCP Server...")

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
        from wet_mcp.sources.crawler import shutdown_crawler

        await shutdown_crawler()
    except Exception as exc:
        logger.debug(f"Browser pool shutdown error (non-fatal): {exc}")

    stop_searxng()


# --- Helpers ---


async def _embed(text: str) -> list[float] | None:
    """Embed text if model is available, truncated to fixed dims."""
    if not _embedding_model:
        return None
    from wet_mcp.embedder import embed_single

    try:
        vec = await asyncio.to_thread(
            embed_single, text, _embedding_model, _embedding_dims
        )
        # Truncate to fixed dims so switching models never breaks the DB
        if _embedding_dims > 0 and len(vec) > _embedding_dims:
            vec = vec[:_embedding_dims]
        return vec
    except Exception as e:
        logger.debug(f"Embedding failed: {e}")
        return None


async def _embed_batch(texts: list[str]) -> list[list[float]] | None:
    """Embed batch of texts if model is available, truncated to fixed dims."""
    if not _embedding_model:
        return None
    from wet_mcp.embedder import embed_texts

    try:
        vecs = await asyncio.to_thread(
            embed_texts, texts, _embedding_model, _embedding_dims
        )
        # Truncate to fixed dims
        if _embedding_dims > 0:
            vecs = [
                v[:_embedding_dims] if len(v) > _embedding_dims else v for v in vecs
            ]
        return vecs
    except Exception as e:
        logger.debug(f"Batch embedding failed: {e}")
        return None


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


@mcp.tool()
async def search(
    action: str,
    query: str | None = None,
    library: str | None = None,
    version: str | None = None,
    categories: str = "general",
    max_results: int = 10,
    limit: int = 10,
) -> str:
    """Search the web, academic papers, or library documentation.
    - search: Web search via SearXNG (requires query)
    - research: Academic/scientific search (requires query)
    - docs: Search library documentation with auto-indexing (requires library + query)
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
            searxng_url = await ensure_searxng()
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


@mcp.tool()
async def extract(
    action: str,
    urls: list[str] | None = None,
    depth: int = 2,
    max_pages: int = 20,
    format: str = "markdown",
    stealth: bool = True,
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


@mcp.tool()
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


@mcp.tool()
async def help(tool_name: str = "search") -> str:
    """Get full documentation for a tool.
    Use when compressed descriptions are insufficient.
    Valid tool names: search, extract, media, help.
    """
    try:
        doc_file = files("wet_mcp.docs").joinpath(f"{tool_name}.md")
        return doc_file.read_text()
    except FileNotFoundError:
        return f"Error: No documentation found for tool '{tool_name}'"
    except Exception as e:
        return f"Error loading documentation: {e}"


# ---------------------------------------------------------------------------
# Research (academic search via SearXNG science category)
# ---------------------------------------------------------------------------


async def _do_research(query: str, max_results: int = 10) -> str:
    """Academic/scientific search using SearXNG science engines."""
    searxng_url = await ensure_searxng()

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
# Docs search (library documentation with auto-indexing)
# ---------------------------------------------------------------------------


async def _do_docs_search(
    library: str,
    query: str,
    version: str | None = None,
    limit: int = 10,
) -> str:
    """Search library documentation. Auto-discovers and indexes if needed."""
    if not _docs_db:
        return "Error: Docs database not initialized"

    # Step 1: Check if library is already indexed
    lib = _docs_db.get_library(library)

    if lib:
        # Check if we have indexed chunks
        ver = _docs_db.get_best_version(lib["id"], version)
        if ver and ver.get("chunk_count", 0) > 0:
            # Search existing index
            query_embedding = await _embed(query)

            results = _docs_db.search(
                query=query,
                library_name=library,
                version=version,
                limit=limit,
                query_embedding=query_embedding,
            )

            if results:
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
    logger.info(f"Library '{library}' not indexed, discovering docs...")

    from wet_mcp.sources.docs import (
        chunk_llms_txt,
        chunk_markdown,
        discover_library,
        fetch_docs_pages,
        try_llms_txt,
    )

    # Discover library metadata from registries
    discovery = await discover_library(library)
    docs_url = ""
    registry = ""
    description = ""

    if discovery:
        docs_url = discovery.get("homepage", "")
        registry = discovery.get("registry", "")
        description = discovery.get("description", "")
    else:
        # Fallback: use SearXNG to find docs
        logger.info(f"Registry lookup failed, trying SearXNG for '{library}'...")
        searxng_url = await ensure_searxng()
        search_result = await searxng_search(
            searxng_url=searxng_url,
            query=f"{library} official documentation",
            categories="general",
            max_results=3,
        )
        try:
            search_data = json.loads(search_result)
            top_results = search_data.get("results", [])
            if top_results:
                docs_url = top_results[0].get("url", "")
        except json.JSONDecodeError:
            pass

    if not docs_url:
        return json.dumps(
            {
                "error": f"Could not find documentation URL for '{library}'",
                "hint": "Try providing the docs URL directly via extract action",
            },
            ensure_ascii=False,
        )

    # Create/update library record
    lib_id = _docs_db.upsert_library(
        name=library,
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

    # Step 3: Fetch and chunk docs
    all_chunks: list[dict] = []
    page_count = 0

    # Tier 0: Try llms.txt (fastest, best quality)
    llms_content = await try_llms_txt(docs_url)
    if llms_content:
        all_chunks = chunk_llms_txt(llms_content, base_url=docs_url)
        page_count = 1
        logger.info(f"Indexed {len(all_chunks)} chunks from llms.txt")
    else:
        # Tier 1: Crawl docs pages
        pages = await fetch_docs_pages(
            docs_url=docs_url,
            query=query,
            max_pages=30,
        )
        page_count = len(pages)

        for page in pages:
            page_chunks = chunk_markdown(
                content=page["content"],
                url=page.get("url", ""),
            )
            # Set title from page if chunk doesn't have one
            for chunk in page_chunks:
                if not chunk.get("title") and page.get("title"):
                    chunk["title"] = page["title"]
            all_chunks.extend(page_chunks)

        logger.info(f"Indexed {len(all_chunks)} chunks from {page_count} pages")

    if not all_chunks:
        return json.dumps(
            {
                "error": f"Could not extract documentation content from {docs_url}",
                "docs_url": docs_url,
            },
            ensure_ascii=False,
        )

    # Step 4: Generate embeddings (optional)
    embeddings = None
    if _embedding_model and all_chunks:
        texts = [c["content"][:500] for c in all_chunks]  # Truncate for embedding
        embeddings = await _embed_batch(texts)
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
    query_embedding = await _embed(query)

    results = _docs_db.search(
        query=query,
        library_name=library,
        version=version,
        limit=limit,
        query_embedding=query_embedding,
    )

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
