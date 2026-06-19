"""SearXNG search integration — delegates to web-core.

Wraps web-core's ``search()`` function to return JSON strings (MCP tool
format) and adds health-check + auto-restart logic before each search.

Internal helpers (``_normalize_url``, ``_apply_domain_cap``, etc.) are
re-exported from web-core for backward compatibility.
"""

import json

import httpx
from loguru import logger

# Re-export URL helpers for backward compat
from web_core.http.url import _TRACKING_PARAMS  # noqa: F401
from web_core.http.url import is_valid_domain as _is_valid_domain  # noqa: F401
from web_core.http.url import normalize_url as _normalize_url  # noqa: F401
from web_core.search import SearchError
from web_core.search import search as _wc_search
from web_core.search.client import (  # noqa: F401
    _apply_domain_cap,
    _build_filtered_query,
)

from wet_mcp.config import settings

# Default health check timeout
_HEALTH_CHECK_TIMEOUT = 5.0


def _searxng_auth() -> tuple[str, str] | None:
    """HTTP basic-auth ``(user, pass)`` for an external authenticated SearXNG
    (e.g. behind Caddy basic-auth), or ``None`` when not both configured — the
    auto-local SearXNG needs none. Avoids embedding credentials in SEARXNG_URL."""
    user = settings.searxng_auth_user
    pwd = settings.searxng_auth_pass
    return (user, pwd) if user and pwd else None


async def _check_health(searxng_url: str) -> bool:
    """Quick health check before issuing a search request.

    Returns True if SearXNG is responsive, False otherwise.
    """
    try:
        auth = _searxng_auth()
        extra = {"auth": auth} if auth else {}
        async with httpx.AsyncClient(timeout=_HEALTH_CHECK_TIMEOUT) as client:
            response = await client.get(
                f"{searxng_url}/healthz",
                headers={
                    "X-Real-IP": "127.0.0.1",
                    "X-Forwarded-For": "127.0.0.1",
                },
                **extra,
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
    time_range: str | None = None,
    language: str | None = None,
    include_domains: list[str] | None = None,
    exclude_domains: list[str] | None = None,
) -> str:
    """Search via SearXNG API — delegates to web-core, returns JSON string.

    Adds health check + auto-restart before each search (MCP-specific).
    web-core's search returns ``list[SearchResult]``; this wrapper converts
    to a JSON string for MCP tool response format.

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

    try:
        import dataclasses

        results = await _wc_search(
            active_url,
            query,
            categories=categories,
            max_results=max_results,
            time_range=time_range,
            language=language,
            include_domains=include_domains,
            exclude_domains=exclude_domains,
            auth=_searxng_auth(),
        )

        output = {
            "results": [dataclasses.asdict(r) for r in results],
            "total": len(results),
            "query": query,
        }

        logger.info(f"Found {len(results)} results for: {query}")
        return json.dumps(output, ensure_ascii=False, indent=2)

    except SearchError as e:
        error_msg = str(e)
        logger.error(f"SearXNG search failed: {error_msg}")

        # On connection errors, try restart + one more attempt
        if "Request error" in error_msg:
            logger.info("Attempting SearXNG restart before final retry...")
            active_url = await _ensure_searxng_healthy(active_url)
            try:
                results = await _wc_search(
                    active_url,
                    query,
                    categories=categories,
                    max_results=max_results,
                    time_range=time_range,
                    language=language,
                    include_domains=include_domains,
                    exclude_domains=exclude_domains,
                )
                output = {
                    "results": [dataclasses.asdict(r) for r in results],
                    "total": len(results),
                    "query": query,
                }
                return json.dumps(output, ensure_ascii=False, indent=2)
            except SearchError:
                pass

        return json.dumps({"error": error_msg})
