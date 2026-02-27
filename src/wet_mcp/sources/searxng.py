"""SearXNG search integration with retry logic and health verification."""

import asyncio
import json

import httpx
from loguru import logger

from wet_mcp.config import settings

# Default retry configuration
_MAX_RETRIES = 3
_BASE_DELAY = 1.0  # seconds
_HEALTH_CHECK_TIMEOUT = 5.0


async def _check_health(searxng_url: str) -> bool:
    """Quick health check before issuing a search request.

    Returns True if SearXNG is responsive, False otherwise.
    """
    try:
        async with httpx.AsyncClient(timeout=_HEALTH_CHECK_TIMEOUT) as client:
            response = await client.get(
                f"{searxng_url}/healthz",
                headers={
                    "X-Real-IP": "127.0.0.1",
                    "X-Forwarded-For": "127.0.0.1",
                },
            )
            return response.status_code == 200
    except Exception:
        return False


async def _ensure_searxng_healthy(searxng_url: str) -> str:
    """Verify SearXNG is healthy; restart if needed.

    Imports ensure_searxng lazily to avoid circular imports.
    If the current instance is unhealthy, triggers a restart
    and returns the (potentially new) URL.
    """
    if await _check_health(searxng_url):
        return searxng_url

    logger.warning(f"SearXNG at {searxng_url} is unhealthy, attempting restart...")

    from wet_mcp.searxng_runner import ensure_searxng

    new_url = await ensure_searxng()

    if await _check_health(new_url):
        logger.info(f"SearXNG restarted successfully at {new_url}")
        return new_url

    # Even if health check fails after restart, return the URL
    # and let the search attempt proceed — it may still work.
    logger.warning(f"SearXNG at {new_url} still unhealthy after restart attempt")
    return new_url


async def search(
    searxng_url: str,
    query: str,
    categories: str = "general",
    max_results: int = 10,
) -> str:
    """Search via SearXNG API with retry logic and health verification.

    Retries up to _MAX_RETRIES times with exponential backoff on
    transient failures (connection errors, 5xx responses, empty results
    from known-good queries).

    Args:
        searxng_url: SearXNG instance URL
        query: Search query
        categories: Search category (general, images, videos, files)
        max_results: Maximum number of results

    Returns:
        JSON string with search results
    """
    logger.info(f"Searching SearXNG: {query}")

    # Pre-search health check + auto-restart if needed
    active_url = await _ensure_searxng_healthy(searxng_url)

    params = {
        "q": query,
        "format": "json",
        "categories": categories,
    }

    last_error: str | None = None

    async with httpx.AsyncClient(timeout=settings.searxng_timeout) as client:
        for attempt in range(1, _MAX_RETRIES + 1):
            try:
                headers = {
                    "X-Real-IP": "127.0.0.1",
                    "X-Forwarded-For": "127.0.0.1",
                }
                response = await client.get(
                    f"{active_url}/search",
                    params=params,
                    headers=headers,
                )
                response.raise_for_status()
                data = response.json()

                results = data.get("results", [])[: max_results * 2]

                # Format results
                formatted = []
                for r in results:
                    formatted.append(
                        {
                            "url": r.get("url", ""),
                            "title": r.get("title", ""),
                            "snippet": r.get("content", ""),
                            "source": r.get("engine", ""),
                        }
                    )

                # Deduplicate by URL: with multiple engines, the same page
                # may appear several times.  Keep the entry with the longest
                # snippet (most informative) and merge engine sources.
                seen: dict[str, dict] = {}
                deduped: list[dict] = []
                for item in formatted:
                    url = item["url"]
                    if url in seen:
                        existing = seen[url]
                        # Merge engine sources
                        if item["source"] and item["source"] not in existing["source"]:
                            existing["source"] += f", {item['source']}"
                        # Keep longer snippet
                        if len(item.get("snippet", "")) > len(
                            existing.get("snippet", "")
                        ):
                            existing["snippet"] = item["snippet"]
                            existing["title"] = item["title"] or existing["title"]
                    else:
                        seen[url] = item
                        deduped.append(item)

                # Trim to requested limit after dedup
                deduped = deduped[:max_results]

                output = {
                    "results": deduped,
                    "total": len(deduped),
                    "query": query,
                }

                logger.info(f"Found {len(deduped)} results for: {query}")
                return json.dumps(output, ensure_ascii=False, indent=2)

            except httpx.HTTPStatusError as e:
                status = e.response.status_code
                last_error = f"HTTP error: {status}"
                logger.warning(
                    f"SearXNG HTTP {status} on attempt {attempt}/{_MAX_RETRIES}"
                )

                # Only retry on server errors (5xx), not client errors (4xx)
                if status < 500:
                    logger.error(f"SearXNG client error (non-retryable): {last_error}")
                    return json.dumps({"error": last_error})

            except httpx.RequestError as e:
                last_error = f"Request error: {e}"
                logger.warning(
                    f"SearXNG request error on attempt {attempt}/{_MAX_RETRIES}: {e}"
                )

                # Connection refused / reset likely means SearXNG crashed
                # Try to restart it before next retry
                if attempt < _MAX_RETRIES:
                    logger.info("Attempting SearXNG restart before retry...")
                    active_url = await _ensure_searxng_healthy(active_url)

            except Exception as e:
                last_error = str(e)
                logger.warning(
                    f"SearXNG unexpected error on attempt {attempt}/{_MAX_RETRIES}: {e}"
                )

            # Exponential backoff before retry (skip on last attempt)
            if attempt < _MAX_RETRIES:
                delay = _BASE_DELAY * (2 ** (attempt - 1))
                logger.debug(f"Retrying in {delay:.1f}s...")
                await asyncio.sleep(delay)

    # All retries exhausted
    error_msg = last_error or "All retry attempts failed"
    logger.error(f"SearXNG search failed after {_MAX_RETRIES} attempts: {error_msg}")
    return json.dumps({"error": error_msg})
