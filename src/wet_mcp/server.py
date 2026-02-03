"""WET MCP Server - Main server definition."""

import sys
from importlib.resources import files

from loguru import logger
from mcp.server.fastmcp import FastMCP

from wet_mcp.config import settings
from wet_mcp.docker_manager import ensure_searxng

# Configure logging
logger.remove()
logger.add(sys.stderr, level=settings.log_level)

# Initialize MCP server
mcp = FastMCP(
    name="wet",
    instructions="Web ExTract MCP Server - search, extract, crawl, map with SearXNG",
)

# Store SearXNG URL after initialization
_searxng_url: str | None = None


def _get_searxng_url() -> str:
    """Get SearXNG URL, initializing container if needed."""
    global _searxng_url
    if _searxng_url is None:
        _searxng_url = ensure_searxng()
    return _searxng_url


@mcp.tool()
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
    from wet_mcp.sources.crawler import crawl, extract, sitemap
    from wet_mcp.sources.searxng import search as searxng_search

    match action:
        case "search":
            if not query:
                return "Error: query is required for search action"
            searxng_url = _get_searxng_url()
            return await searxng_search(
                searxng_url=searxng_url,
                query=query,
                categories=categories,
                max_results=max_results,
            )

        case "extract":
            if not urls:
                return "Error: urls is required for extract action"
            return await extract(
                urls=urls,
                format=format,
                stealth=stealth,
            )

        case "crawl":
            if not urls:
                return "Error: urls is required for crawl action"
            return await crawl(
                urls=urls,
                depth=depth,
                max_pages=max_pages,
                format=format,
                stealth=stealth,
            )

        case "map":
            if not urls:
                return "Error: urls is required for map action"
            return await sitemap(
                urls=urls,
                depth=depth,
                max_pages=max_pages,
            )

        case _:
            return f"Error: Unknown action '{action}'. Valid actions: search, extract, crawl, map"


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
    from wet_mcp.sources.crawler import download_media, list_media

    match action:
        case "list":
            if not url:
                return "Error: url is required for list action"
            return await list_media(
                url=url,
                media_type=media_type,
                max_items=max_items,
            )

        case "download":
            if not media_urls:
                return "Error: media_urls is required for download action"
            return await download_media(
                media_urls=media_urls,
                output_dir=output_dir or settings.download_dir,
            )

        case "analyze":
            if not url:
                return "Error: url (local path) is required for analyze action"

            from wet_mcp.llm import analyze_media

            return await analyze_media(media_path=url, prompt=prompt)

        case _:
            return f"Error: Unknown action '{action}'. Valid actions: list, download, analyze"


@mcp.tool()
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
    """Run the MCP server."""
    from wet_mcp.setup import run_auto_setup

    logger.info("Starting WET MCP Server...")

    # Run auto-setup on first start (installs Playwright, etc.)
    run_auto_setup()

    # Setup LLM API Keys
    settings.setup_api_keys()

    # Initialize SearXNG container
    searxng_url = _get_searxng_url()
    logger.info(f"SearXNG URL: {searxng_url}")

    # Run MCP server
    mcp.run()


if __name__ == "__main__":
    main()
