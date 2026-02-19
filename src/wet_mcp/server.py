"""WET MCP Server - Main server definition."""

import asyncio
import sys
from contextlib import asynccontextmanager
from importlib.resources import files

import mcp.types as types
from loguru import logger
from mcp.server.fastmcp import FastMCP

from wet_mcp.config import settings
from wet_mcp.searxng_runner import ensure_searxng, stop_searxng
from wet_mcp.sources.crawler import crawl, extract, list_media, sitemap
from wet_mcp.sources.searxng import search as searxng_search

# Configure logging
logger.remove()
logger.add(sys.stderr, level=settings.log_level, serialize=True)


@asynccontextmanager
async def _lifespan(_server: FastMCP):
    """Server lifespan: startup SearXNG, cleanup on shutdown."""
    from wet_mcp.setup import run_auto_setup

    logger.info("Starting WET MCP Server...")
    await asyncio.to_thread(run_auto_setup)
    settings.setup_api_keys()

    # Pre-import crawl4ai — its first import runs heavy synchronous init
    # that would block the event loop if deferred to the first tool call.
    logger.info("Pre-loading Crawl4AI...")
    await asyncio.to_thread(__import__, "crawl4ai")
    logger.info("Crawl4AI loaded")

    searxng_url = await ensure_searxng()
    logger.info(f"SearXNG URL: {searxng_url}")

    yield

    logger.info("Shutting down WET MCP Server...")

    # Shut down the shared browser pool first (may take a few seconds)
    try:
        from wet_mcp.sources.crawler import shutdown_crawler

        await shutdown_crawler()
    except Exception as exc:
        logger.debug(f"Browser pool shutdown error (non-fatal): {exc}")

    stop_searxng()


# Initialize MCP server
mcp = FastMCP(
    name="wet",
    instructions="Web ExTract MCP Server - search, extract, crawl, map with SearXNG",
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

    # Hard timeout — cancel and wait briefly for cleanup
    task.cancel()
    logger.warning(f"Tool '{action}' timed out after {timeout}s, cancelling...")

    # Give the task a grace period to clean up (close browser pages, etc.)
    try:
        await asyncio.wait_for(asyncio.shield(task), timeout=_CANCEL_GRACE_PERIOD)
    except (asyncio.CancelledError, TimeoutError, Exception):
        # Task either cancelled cleanly, timed out again, or raised — all OK
        pass

    logger.error(f"Tool '{action}' timed out after {timeout}s")
    return (
        f"Error: '{action}' timed out after {timeout}s. "
        "Increase TOOL_TIMEOUT or try simpler parameters."
    )


@mcp.tool(
    annotations=types.ToolAnnotations(
        readOnlyHint=True, destructiveHint=False, idempotentHint=True
    )
)
async def web(
    action: str,
    query: str | None = None,
    urls: list[str] | None = None,
    categories: str = "general",
    max_results: int = 10,
    depth: int = 2,
    max_pages: int = 20,
    format: str = "markdown",
    stealth: bool = True,
) -> str:
    """Web operations: search, extract, crawl, map.
    - search: Web search via SearXNG (requires query)
    - extract: Get clean content from URLs
    - crawl: Deep crawl from root URL
    - map: Discover site structure
    Use `help` tool for full documentation.
    """
    match action:
        case "search":
            if not query:
                return "Error: query is required for search action"
            searxng_url = await ensure_searxng()
            return await _with_timeout(
                searxng_search(
                    searxng_url=searxng_url,
                    query=query,
                    categories=categories,
                    max_results=max_results,
                ),
                "search",
            )

        case "extract":
            if not urls:
                return "Error: urls is required for extract action"
            return await _with_timeout(
                extract(urls=urls, format=format, stealth=stealth),
                "extract",
            )

        case "crawl":
            if not urls:
                return "Error: urls is required for crawl action"
            return await _with_timeout(
                crawl(
                    urls=urls,
                    depth=depth,
                    max_pages=max_pages,
                    format=format,
                    stealth=stealth,
                ),
                "crawl",
            )

        case "map":
            if not urls:
                return "Error: urls is required for map action"
            return await _with_timeout(
                sitemap(urls=urls, depth=depth, max_pages=max_pages),
                "map",
            )

        case _:
            return f"Error: Unknown action '{action}'. Valid actions: search, extract, crawl, map"


@mcp.tool(
    annotations=types.ToolAnnotations(
        readOnlyHint=False, destructiveHint=False, idempotentHint=False
    )
)
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
    annotations=types.ToolAnnotations(
        readOnlyHint=True, destructiveHint=False, idempotentHint=True
    )
)
async def help(tool_name: str = "web") -> str:
    """Get full documentation for a tool.
    Use when compressed descriptions are insufficient.
    """
    try:
        doc_file = files("wet_mcp.docs").joinpath(f"{tool_name}.md")
        return doc_file.read_text()
    except FileNotFoundError:
        return f"Error: No documentation found for tool '{tool_name}'"
    except Exception as e:
        return f"Error loading documentation: {e}"


def main() -> None:
    """Entry point for the MCP server."""
    mcp.run()


if __name__ == "__main__":
    main()
