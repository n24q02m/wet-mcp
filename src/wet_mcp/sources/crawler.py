"""Crawl4AI integration for web crawling and extraction."""

import json
from pathlib import Path

from loguru import logger


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
    from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig

    logger.info(f"Extracting content from {len(urls)} URLs")

    browser_config = BrowserConfig(
        headless=True,
        enable_stealth=stealth,
        verbose=False,
    )

    results = []

    async with AsyncWebCrawler(verbose=False, config=browser_config) as crawler:
        for url in urls:
            try:
                result = await crawler.arun(
                    url,
                    config=CrawlerRunConfig(verbose=False),
                )

                if result.success:
                    content = (
                        result.markdown if format == "markdown" else result.cleaned_html
                    )
                    results.append(
                        {
                            "url": url,
                            "title": result.metadata.get("title", ""),
                            "content": content,
                            "links": {
                                "internal": result.links.get("internal", [])[:20],
                                "external": result.links.get("external", [])[:20],
                            },
                        }
                    )
                else:
                    results.append(
                        {
                            "url": url,
                            "error": result.error_message or "Failed to extract",
                        }
                    )

            except Exception as e:
                logger.error(f"Error extracting {url}: {e}")
                results.append(
                    {
                        "url": url,
                        "error": str(e),
                    }
                )

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
    from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig

    logger.info(f"Crawling {len(urls)} URLs with depth={depth}")

    browser_config = BrowserConfig(
        headless=True,
        enable_stealth=stealth,
        verbose=False,
    )

    all_results = []
    visited = set()

    async with AsyncWebCrawler(verbose=False, config=browser_config) as crawler:
        for root_url in urls:
            to_crawl = [(root_url, 0)]

            while to_crawl and len(all_results) < max_pages:
                url, current_depth = to_crawl.pop(0)

                if url in visited or current_depth > depth:
                    continue

                visited.add(url)

                try:
                    result = await crawler.arun(
                        url,
                        config=CrawlerRunConfig(verbose=False),
                    )

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
    from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig

    logger.info(f"Mapping {len(urls)} URLs")

    browser_config = BrowserConfig(headless=True, verbose=False)

    all_urls = []
    visited = set()

    async with AsyncWebCrawler(verbose=False, config=browser_config) as crawler:
        for root_url in urls:
            to_visit = [(root_url, 0)]
            site_urls = []

            while to_visit and len(site_urls) < max_pages:
                url, current_depth = to_visit.pop(0)

                if url in visited or current_depth > depth:
                    continue

                visited.add(url)
                site_urls.append({"url": url, "depth": current_depth})

                try:
                    result = await crawler.arun(
                        url,
                        config=CrawlerRunConfig(verbose=False),
                    )

                    if result.success and current_depth < depth:
                        for link in result.links.get("internal", [])[:20]:
                            if link not in visited:
                                to_visit.append((link, current_depth + 1))

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
    from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig

    logger.info(f"Listing media from: {url}")

    browser_config = BrowserConfig(headless=True, verbose=False)

    async with AsyncWebCrawler(verbose=False, config=browser_config) as crawler:
        result = await crawler.arun(
            url,
            config=CrawlerRunConfig(verbose=False),
        )

        if not result.success:
            return json.dumps({"error": result.error_message or "Failed to load page"})

        media = result.media or {}

        output = {}

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
) -> str:
    """Download media files.

    Args:
        media_urls: List of media URLs to download
        output_dir: Output directory

    Returns:
        JSON string with download results
    """
    import httpx

    logger.info(f"Downloading {len(media_urls)} media files")

    output_path = Path(output_dir).expanduser()
    output_path.mkdir(parents=True, exist_ok=True)

    results = []

    async with httpx.AsyncClient(timeout=60) as client:
        for url in media_urls:
            try:
                response = await client.get(url)
                response.raise_for_status()

                filename = url.split("/")[-1].split("?")[0] or "download"
                filepath = output_path / filename

                filepath.write_bytes(response.content)

                results.append(
                    {
                        "url": url,
                        "path": str(filepath),
                        "size": len(response.content),
                    }
                )

            except Exception as e:
                logger.error(f"Error downloading {url}: {e}")
                results.append(
                    {
                        "url": url,
                        "error": str(e),
                    }
                )

    logger.info(f"Downloaded {len([r for r in results if 'path' in r])} files")
    return json.dumps(results, ensure_ascii=False, indent=2)
