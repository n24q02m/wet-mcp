"""Crawl4AI integration for web crawling and extraction.

Uses a singleton browser pool to reuse a single browser instance across
requests instead of starting/stopping the browser on every call.  This
dramatically improves reliability and performance.

Concurrency is bounded by a semaphore so that parallel tool calls do not
overwhelm the browser or exhaust system memory.
"""

import asyncio
import json
import os
import tempfile
from pathlib import Path

import httpx
from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig
from loguru import logger

from wet_mcp.security import is_safe_url

# ---------------------------------------------------------------------------
# Browser pool (singleton)
# ---------------------------------------------------------------------------

# Per-process browser data directory to prevent Playwright lock deadlock
# when multiple MCP server instances run simultaneously.
_BROWSER_DATA_DIR = str(Path(tempfile.gettempdir()) / f"wet-mcp-browser-{os.getpid()}")

# Maximum number of concurrent browser operations.  Each operation uses a
# tab/page inside the shared browser, so we can safely allow several in
# parallel without starting extra browser processes.
_MAX_CONCURRENT_OPS = 6

# Guards all access to the shared crawler instance.
_pool_lock = asyncio.Lock()
_crawler_instance: AsyncWebCrawler | None = None
_crawler_stealth: bool = False  # stealth mode of the current instance

# Semaphore to limit concurrent browser operations across all callers.
_browser_semaphore: asyncio.Semaphore | None = None


def _browser_config(stealth: bool = False) -> BrowserConfig:
    """Create BrowserConfig with per-process isolated data directory."""
    return BrowserConfig(
        headless=True,
        enable_stealth=stealth,
        verbose=False,
        user_data_dir=_BROWSER_DATA_DIR,
    )


def _get_semaphore() -> asyncio.Semaphore:
    """Return the module-level semaphore, creating it lazily.

    The semaphore is created lazily because it must be bound to the
    running event loop at creation time.
    """
    global _browser_semaphore
    if _browser_semaphore is None:
        _browser_semaphore = asyncio.Semaphore(_MAX_CONCURRENT_OPS)
    return _browser_semaphore


async def _get_crawler(stealth: bool = False) -> AsyncWebCrawler:
    """Return a shared AsyncWebCrawler, creating one if necessary.

    If the requested *stealth* mode differs from the current instance the
    old browser is shut down and a new one is started.  This should rarely
    happen in practice since most calls use the same stealth setting.
    """
    global _crawler_instance, _crawler_stealth

    async with _pool_lock:
        # Reuse existing instance if stealth matches
        if _crawler_instance is not None and _crawler_stealth == stealth:
            return _crawler_instance

        # Tear down existing instance with different stealth mode
        if _crawler_instance is not None:
            logger.debug(f"Recycling browser (stealth {_crawler_stealth} -> {stealth})")
            try:
                await _crawler_instance.__aexit__(None, None, None)
            except Exception as exc:
                logger.debug(f"Error closing old crawler: {exc}")
            _crawler_instance = None

        # Start a fresh browser
        logger.info(f"Starting shared browser (stealth={stealth})...")
        crawler = AsyncWebCrawler(
            verbose=False,
            config=_browser_config(stealth),
        )
        try:
            await crawler.__aenter__()
        except Exception:
            logger.error("Failed to start shared browser")
            raise

        _crawler_instance = crawler
        _crawler_stealth = stealth
        logger.info("Shared browser started")
        return _crawler_instance


async def shutdown_crawler() -> None:
    """Shut down the shared browser (called during server shutdown)."""
    global _crawler_instance, _browser_semaphore

    async with _pool_lock:
        if _crawler_instance is not None:
            logger.info("Shutting down shared browser...")
            try:
                await _crawler_instance.__aexit__(None, None, None)
            except Exception as exc:
                logger.debug(f"Error during browser shutdown: {exc}")
            _crawler_instance = None
            logger.info("Shared browser shut down")
        _browser_semaphore = None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def extract(
    urls: list[str],
    format: str = "markdown",
    stealth: bool = True,
) -> str:
    """Extract content from URLs.

    Args:
        urls: List of URLs to extract
        format: Output format (markdown, text, html)
        stealth: Enable stealth mode

    Returns:
        JSON string with extracted content
    """
    logger.info(f"Extracting content from {len(urls)} URLs")

    crawler = await _get_crawler(stealth)
    sem = _get_semaphore()

    async def process_url(url: str):
        async with sem:
            if not is_safe_url(url):
                logger.warning(f"Skipping unsafe URL: {url}")
                return {"url": url, "error": "Security Alert: Unsafe URL blocked"}

            try:
                result = await crawler.arun(
                    url,  # ty: ignore[invalid-argument-type]
                    config=CrawlerRunConfig(verbose=False),
                )  # ty: ignore[missing-argument]

                if result.success:
                    content = (
                        result.markdown if format == "markdown" else result.cleaned_html
                    )
                    return {
                        "url": url,
                        "title": result.metadata.get("title", ""),
                        "content": content,
                        "links": {
                            "internal": result.links.get("internal", [])[:20],
                            "external": result.links.get("external", [])[:20],
                        },
                    }
                else:
                    return {
                        "url": url,
                        "error": result.error_message or "Failed to extract",
                    }

            except Exception as e:
                logger.error(f"Error extracting {url}: {e}")
                return {
                    "url": url,
                    "error": str(e),
                }

    tasks = [process_url(url) for url in urls]
    results = await asyncio.gather(*tasks)

    logger.info(f"Extracted {len(results)} pages")
    return json.dumps(results, ensure_ascii=False, indent=2)


async def crawl(
    urls: list[str],
    depth: int = 2,
    max_pages: int = 20,
    format: str = "markdown",
    stealth: bool = True,
) -> str:
    """Deep crawl from root URLs.

    Args:
        urls: List of root URLs
        depth: Crawl depth
        max_pages: Maximum pages to crawl
        format: Output format
        stealth: Enable stealth mode

    Returns:
        JSON string with crawled content
    """
    logger.info(f"Crawling {len(urls)} URLs with depth={depth}")

    all_results = []
    visited: set[str] = set()

    crawler = await _get_crawler(stealth)
    sem = _get_semaphore()

    for root_url in urls:
        if not is_safe_url(root_url):
            logger.warning(f"Skipping unsafe URL: {root_url}")
            continue

        to_crawl: list[tuple[str, int]] = [(root_url, 0)]

        while to_crawl and len(all_results) < max_pages:
            url, current_depth = to_crawl.pop(0)

            if url in visited or current_depth > depth:
                continue

            visited.add(url)

            async with sem:
                try:
                    result = await crawler.arun(
                        url,  # ty: ignore[invalid-argument-type]
                        config=CrawlerRunConfig(verbose=False),
                    )  # ty: ignore[missing-argument]

                    if result.success:
                        content = (
                            result.markdown
                            if format == "markdown"
                            else result.cleaned_html
                        )
                        all_results.append(
                            {
                                "url": url,
                                "depth": current_depth,
                                "title": result.metadata.get("title", ""),
                                "content": content[:5000],  # Limit content size
                            }
                        )

                        # Add internal links for next depth
                        if current_depth < depth:
                            internal_links = result.links.get("internal", [])
                            for link_item in internal_links[:10]:
                                # Crawl4AI returns dicts with 'href' key
                                link_url = (
                                    link_item.get("href", "")
                                    if isinstance(link_item, dict)
                                    else link_item
                                )
                                if link_url and link_url not in visited:
                                    to_crawl.append((link_url, current_depth + 1))

                except Exception as e:
                    logger.error(f"Error crawling {url}: {e}")

    logger.info(f"Crawled {len(all_results)} pages")
    return json.dumps(all_results, ensure_ascii=False, indent=2)


async def sitemap(
    urls: list[str],
    depth: int = 2,
    max_pages: int = 50,
) -> str:
    """Discover site structure.

    Args:
        urls: List of root URLs
        depth: Discovery depth
        max_pages: Maximum pages to discover

    Returns:
        JSON string with discovered URLs
    """
    logger.info(f"Mapping {len(urls)} URLs")

    all_urls: list[dict[str, object]] = []
    visited: set[str] = set()

    crawler = await _get_crawler(stealth=False)
    sem = _get_semaphore()

    for root_url in urls:
        if not is_safe_url(root_url):
            logger.warning(f"Skipping unsafe URL: {root_url}")
            continue

        to_visit: list[tuple[str, int]] = [(root_url, 0)]
        site_urls: list[dict[str, object]] = []

        while to_visit and len(site_urls) < max_pages:
            url, current_depth = to_visit.pop(0)

            if url in visited or current_depth > depth:
                continue

            visited.add(url)
            site_urls.append({"url": url, "depth": current_depth})

            async with sem:
                try:
                    result = await crawler.arun(
                        url,  # ty: ignore[invalid-argument-type]
                        config=CrawlerRunConfig(verbose=False),
                    )  # ty: ignore[missing-argument]

                    if result.success and current_depth < depth:
                        for link in result.links.get("internal", [])[:20]:
                            # Extract URL from dict if necessary
                            link_url = (
                                link.get("href", "") if isinstance(link, dict) else link
                            )
                            if link_url and link_url not in visited:
                                to_visit.append((link_url, current_depth + 1))

                except Exception as e:
                    logger.debug(f"Error mapping {url}: {e}")

        all_urls.extend(site_urls)

    logger.info(f"Mapped {len(all_urls)} URLs")
    return json.dumps(all_urls, ensure_ascii=False, indent=2)


async def list_media(
    url: str,
    media_type: str = "all",
    max_items: int = 10,
) -> str:
    """List media from a page.

    Args:
        url: Page URL to scan
        media_type: Type of media (images, videos, audio, files, all)
        max_items: Maximum items to return

    Returns:
        JSON string with media list
    """
    logger.info(f"Listing media from: {url}")

    if not is_safe_url(url):
        return json.dumps({"error": "Security Alert: Unsafe URL blocked"})

    crawler = await _get_crawler(stealth=False)
    sem = _get_semaphore()

    async with sem:
        result = await crawler.arun(
            url,  # ty: ignore[invalid-argument-type]
            config=CrawlerRunConfig(verbose=False),
        )  # ty: ignore[missing-argument]

        if not result.success:
            return json.dumps({"error": result.error_message or "Failed to load page"})

        media = result.media or {}

        output: dict[str, list] = {}

        if media_type in ("images", "all"):
            output["images"] = media.get("images", [])[:max_items]
        if media_type in ("videos", "all"):
            output["videos"] = media.get("videos", [])[:max_items]
        if media_type in ("audio", "all"):
            # Crawl4AI uses 'audios' (plural)
            output["audio"] = media.get("audios", [])[:max_items]

        logger.info(f"Found media: {sum(len(v) for v in output.values())} items")
        return json.dumps(output, ensure_ascii=False, indent=2)


async def download_media(
    media_urls: list[str],
    output_dir: str,
    concurrency: int = 5,
) -> str:
    """Download media files.

    Args:
        media_urls: List of media URLs to download
        output_dir: Output directory
        concurrency: Max concurrent downloads

    Returns:
        JSON string with download results
    """
    logger.info(f"Downloading {len(media_urls)} media files")

    output_path = Path(output_dir).expanduser().resolve()
    output_path.mkdir(parents=True, exist_ok=True)

    transport = httpx.AsyncHTTPTransport(retries=3)
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        )
    }

    semaphore = asyncio.Semaphore(concurrency)

    async def _download_one(url: str, client: httpx.AsyncClient) -> dict:
        async with semaphore:
            try:
                # Handle protocol-relative URLs
                target_url = url
                if target_url.startswith("//"):
                    target_url = f"https:{target_url}"

                if not is_safe_url(target_url):
                    return {"url": url, "error": "Security Alert: Unsafe URL blocked"}

                # Use stream to avoid loading large files into memory
                async with client.stream(
                    "GET", target_url, follow_redirects=True
                ) as response:
                    response.raise_for_status()

                    filename = target_url.split("/")[-1].split("?")[0] or "download"
                    filepath = (output_path / filename).resolve()

                    # Security check: Ensure the resolved path is still
                    # within the output directory
                    if not filepath.is_relative_to(output_path):
                        raise ValueError(
                            f"Security Alert: Path traversal attempt detected "
                            f"for {filename}"
                        )

                    # Write chunks in thread to avoid blocking event loop
                    total_size = 0
                    with open(filepath, "wb") as f:
                        async for chunk in response.aiter_bytes():
                            await asyncio.to_thread(f.write, chunk)
                            total_size += len(chunk)

                    return {
                        "url": url,
                        "path": str(filepath),
                        "size": total_size,
                    }

            except Exception as e:
                logger.error(f"Error downloading {url}: {e}")
                return {
                    "url": url,
                    "error": str(e),
                }

    async with httpx.AsyncClient(
        timeout=60, transport=transport, headers=headers
    ) as client:
        tasks = [_download_one(url, client) for url in media_urls]
        results = await asyncio.gather(*tasks)

    logger.info(f"Downloaded {len([r for r in results if 'path' in r])} files")
    return json.dumps(results, ensure_ascii=False, indent=2)
