"""SearXNG search integration with retry logic and health verification."""

import asyncio
import json
from urllib.parse import parse_qs, urlencode, urlparse

import httpx
from loguru import logger

from wet_mcp.config import settings

# Default retry configuration
_MAX_RETRIES = 3
_BASE_DELAY = 1.0  # seconds
_HEALTH_CHECK_TIMEOUT = 5.0
_MAX_PER_DOMAIN = 3

# Tracking parameters to strip during URL normalization
_TRACKING_PARAMS = frozenset(
    {
        "utm_source",
        "utm_medium",
        "utm_campaign",
        "utm_term",
        "utm_content",
        "fbclid",
        "gclid",
        "msclkid",
        "yclid",
        "ref",
        "_ga",
        "_gl",
        "mc_cid",
        "mc_eid",
    }
)


def _normalize_url(url: str) -> str:
    """Normalize a URL for deduplication.

    Strips www. prefix, trailing slashes, and known tracking parameters.
    """
    if not url:
        return ""

    parsed = urlparse(url)

    # Strip www. from netloc
    netloc = parsed.netloc
    if netloc.startswith("www."):
        netloc = netloc[4:]

    # Strip trailing slash from path
    path = parsed.path.rstrip("/")

    # Remove tracking params
    if parsed.query:
        params = parse_qs(parsed.query, keep_blank_values=True)
        cleaned = {k: v for k, v in params.items() if k not in _TRACKING_PARAMS}
        query = urlencode(cleaned, doseq=True)
    else:
        query = ""

    # Reconstruct URL
    result = (
        f"{parsed.scheme}://{netloc}{path}"
        if parsed.scheme and netloc
        else f"{netloc}{path}"
    )
    if query:
        result += f"?{query}"
    return result


def _apply_domain_cap(items: list[dict]) -> list[dict]:
    """Limit results to _MAX_PER_DOMAIN per domain, preserving order."""
    domain_counts: dict[str, int] = {}
    result: list[dict] = []
    for item in items:
        parsed = urlparse(item.get("url", ""))
        domain = parsed.netloc
        if domain.startswith("www."):
            domain = domain[4:]
        count = domain_counts.get(domain, 0)
        if count < _MAX_PER_DOMAIN:
            result.append(item)
            domain_counts[domain] = count + 1
    return result


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


def _build_filtered_query(
    query: str,
    include_domains: list[str] | None = None,
    exclude_domains: list[str] | None = None,
) -> str:
    """Build query string with domain include/exclude filters."""
    parts = [query]
    if include_domains:
        site_filter = " OR ".join(f"site:{d}" for d in include_domains[:5])
        parts = [f"({site_filter}) {query}"]
    if exclude_domains:
        for domain in exclude_domains[:10]:
            parts.append(f"-site:{domain}")
    return " ".join(parts)


async def search(
    searxng_url: str,
    query: str,
    categories: str = "general",
    max_results: int = 10,
    time_range: str | None = None,
    language: str | None = None,
    include_domains: list[str] | None = None,
    exclude_domains: list[str] | None = None,
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
        time_range: Time filter (day, week, month, year)
        language: Language filter (e.g. en, vi, zh)
        include_domains: Only search these domains (max 5)
        exclude_domains: Exclude these domains (max 10)

    Returns:
        JSON string with search results
    """
    logger.info(f"Searching SearXNG: {query}")

    # Pre-search health check + auto-restart if needed
    active_url = await _ensure_searxng_healthy(searxng_url)

    effective_query = _build_filtered_query(query, include_domains, exclude_domains)

    params = {
        "q": effective_query,
        "format": "json",
        "categories": categories,
    }
    if time_range and time_range in ("day", "week", "month", "year"):
        params["time_range"] = time_range
    if language:
        params["language"] = language

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

                # Deduplicate by normalized URL: with multiple engines, the same
                # page may appear several times.  Keep the entry with the longest
                # snippet (most informative) and merge engine sources.
                # Python 3.7+ preserves dictionary insertion order, eliminating the need
                # for a separate 'deduped' list mapping to track the first-seen order.
                seen: dict[str, dict] = {}
                for item in formatted:
                    norm_url = _normalize_url(item["url"])
                    if norm_url in seen:
                        existing = seen[norm_url]
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
                        seen[norm_url] = item

                # Apply per-domain cap, then trim to requested limit
                deduped = _apply_domain_cap(list(seen.values()))[:max_results]

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
