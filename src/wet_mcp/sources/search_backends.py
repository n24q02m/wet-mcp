"""Pluggable web-search backends. Default SearXNG (local), Tavily (cloud) for CF
where SearXNG cannot run. All return the same JSON string {results, total, query}
| {error} that server.py's search action already expects from searxng.search().
"""

from __future__ import annotations

import json
import os
from typing import Protocol

import httpx
from loguru import logger
from mcp_core.chains import run_with_fallback

from wet_mcp.config import settings


class SearchBackend(Protocol):
    async def search(
        self,
        query: str,
        max_results: int = 10,
        time_range: str | None = None,
        language: str | None = None,
        include_domains: list[str] | None = None,
        exclude_domains: list[str] | None = None,
        categories: str = "general",
    ) -> str: ...


class SearxngBackend:
    def __init__(self, url: str) -> None:
        self.url = url

    async def search(
        self,
        query: str,
        max_results: int = 10,
        time_range=None,
        language=None,
        include_domains=None,
        exclude_domains=None,
        categories="general",
    ) -> str:
        from wet_mcp.sources.searxng import search as searxng_search

        return await searxng_search(
            searxng_url=self.url,
            query=query,
            categories=categories,
            max_results=max_results,
            time_range=time_range,
            language=language,
            include_domains=include_domains,
            exclude_domains=exclude_domains,
        )


class TavilyBackend:
    _URL = "https://api.tavily.com/search"

    def __init__(self, api_key: str) -> None:
        self.api_key = api_key

    async def search(
        self,
        query: str,
        max_results: int = 10,
        time_range=None,
        language=None,
        include_domains=None,
        exclude_domains=None,
        categories="general",
    ) -> str:
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(
                    self._URL,
                    json={
                        "api_key": self.api_key,
                        "query": query,
                        "max_results": max_results,
                        "search_depth": "basic",
                    },
                )
                if resp.status_code != 200:
                    return json.dumps({"error": f"Tavily HTTP {resp.status_code}"})
                results = resp.json().get("results", [])
                mapped = [
                    {
                        "url": r.get("url", ""),
                        "title": r.get("title", ""),
                        "snippet": r.get("content", r.get("title", "")),
                        "source": "tavily",
                    }
                    for r in results
                ]
                return json.dumps(
                    {"results": mapped, "total": len(mapped), "query": query},
                    ensure_ascii=False,
                    indent=2,
                )
        except httpx.HTTPError as e:  # network/transport — never echo the message (may carry the request body/key)
            return json.dumps({"error": f"Tavily request failed: {type(e).__name__}"})
        except Exception as e:  # tool contract: error string, never raise; type name only (no key leak)
            return json.dumps({"error": f"Tavily search failed: {type(e).__name__}"})


class BraveBackend:
    """Brave Web Search API (https://api.search.brave.com/res/v1/web/search).

    GET with header ``X-Subscription-Token``; results live at ``web.results[]``
    (verified against current Brave docs 2026-06-19).
    """

    _URL = "https://api.search.brave.com/res/v1/web/search"

    def __init__(self, api_key: str) -> None:
        self.api_key = api_key

    async def search(
        self,
        query: str,
        max_results: int = 10,
        time_range=None,
        language=None,
        include_domains=None,
        exclude_domains=None,
        categories="general",
    ) -> str:
        params: dict[str, str | int] = {
            "q": query,
            "count": min(max(max_results, 1), 20),
        }
        if time_range:
            # Brave freshness codes: pd (day) / pw (week) / pm (month) / py (year).
            freshness = {"day": "pd", "week": "pw", "month": "pm", "year": "py"}.get(
                time_range
            )
            if freshness:
                params["freshness"] = freshness
        if language:
            params["search_lang"] = language
        headers = {"X-Subscription-Token": self.api_key, "Accept": "application/json"}
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.get(self._URL, params=params, headers=headers)
                if resp.status_code != 200:
                    return json.dumps({"error": f"Brave HTTP {resp.status_code}"})
                results = resp.json().get("web", {}).get("results", [])
                mapped = [
                    {
                        "url": r.get("url", ""),
                        "title": r.get("title", ""),
                        "snippet": r.get("description", r.get("title", "")),
                        "source": "brave",
                    }
                    for r in results
                ]
                return json.dumps(
                    {"results": mapped, "total": len(mapped), "query": query},
                    ensure_ascii=False,
                    indent=2,
                )
        except (
            httpx.HTTPError
        ) as e:  # transport — type name only (never echo, may carry the token)
            return json.dumps({"error": f"Brave request failed: {type(e).__name__}"})
        except (
            Exception
        ) as e:  # tool contract: error string, never raise; type name only
            return json.dumps({"error": f"Brave search failed: {type(e).__name__}"})


class ExaBackend:
    """Exa search API (https://api.exa.ai/search).

    POST with header ``x-api-key``; body ``{query, numResults}`` plus a small
    ``contents.text`` request so each result carries a snippet. Results live at
    ``results[]`` (verified against current Exa docs 2026-06-19).
    """

    _URL = "https://api.exa.ai/search"

    def __init__(self, api_key: str) -> None:
        self.api_key = api_key

    async def search(
        self,
        query: str,
        max_results: int = 10,
        time_range=None,
        language=None,
        include_domains=None,
        exclude_domains=None,
        categories="general",
    ) -> str:
        body: dict[str, object] = {
            "query": query,
            "numResults": min(max(max_results, 1), 100),
            "contents": {"text": {"maxCharacters": 300}},
        }
        if include_domains:
            body["includeDomains"] = include_domains
        if exclude_domains:
            body["excludeDomains"] = exclude_domains
        headers = {"x-api-key": self.api_key, "Content-Type": "application/json"}
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(self._URL, json=body, headers=headers)
                if resp.status_code != 200:
                    return json.dumps({"error": f"Exa HTTP {resp.status_code}"})
                results = resp.json().get("results", [])
                mapped = [
                    {
                        "url": r.get("url", ""),
                        "title": r.get("title", ""),
                        "snippet": (r.get("text") or r.get("title", ""))[:300],
                        "source": "exa",
                    }
                    for r in results
                ]
                return json.dumps(
                    {"results": mapped, "total": len(mapped), "query": query},
                    ensure_ascii=False,
                    indent=2,
                )
        except (
            httpx.HTTPError
        ) as e:  # transport — type name only (never echo, may carry the key)
            return json.dumps({"error": f"Exa request failed: {type(e).__name__}"})
        except (
            Exception
        ) as e:  # tool contract: error string, never raise; type name only
            return json.dumps({"error": f"Exa search failed: {type(e).__name__}"})


def _make_backend(name: str, searxng_url: str | None = None) -> SearchBackend:
    """Construct a single backend by name. Raises ValueError on missing key/unknown.

    ``searxng_url`` overrides ``settings.searxng_url`` for the SearXNG backend
    (the live auto-started URL, which may use a dynamic port) without mutating
    the global settings.
    """
    if name == "searxng":
        return SearxngBackend(searxng_url or settings.searxng_url)
    if name == "tavily":
        key = os.getenv("TAVILY_API_KEY", settings.tavily_api_key)
        if not key:
            raise ValueError("TAVILY_API_KEY required for the tavily search backend")
        return TavilyBackend(key)
    if name == "brave":
        key = os.getenv("BRAVE_API_KEY", settings.brave_api_key)
        if not key:
            raise ValueError("BRAVE_API_KEY required for the brave search backend")
        return BraveBackend(key)
    if name == "exa":
        key = os.getenv("EXA_API_KEY", settings.exa_api_key)
        if not key:
            raise ValueError("EXA_API_KEY required for the exa search backend")
        return ExaBackend(key)
    raise ValueError(f"Unknown search backend: {name}")


def search_backend_from_env() -> SearchBackend:
    """Single-backend resolver (back-compat). Raises on missing key/unknown name."""
    name = (os.getenv("SEARCH_BACKEND", settings.search_backend) or "searxng").lower()
    return _make_backend(name)


def chain_backend_names() -> list[str]:
    """The ordered backend names in the chain (no construction, no keys needed).

    Reads the CSV ``SEARCH_BACKENDS``; empty -> the single ``SEARCH_BACKEND``
    (back-compat). Used to decide whether the embedded SearXNG must be started
    before running the chain.
    """
    raw = (os.getenv("SEARCH_BACKENDS", settings.search_backends) or "").strip()
    if not raw:
        raw = (
            os.getenv("SEARCH_BACKEND", settings.search_backend) or "searxng"
        ).strip()
    return [n.strip().lower() for n in raw.split(",") if n.strip()]


def search_backends_from_env(searxng_url: str | None = None) -> list[SearchBackend]:
    """Resolve the ordered SEARCH_BACKENDS chain.

    Reads the CSV ``SEARCH_BACKENDS``; empty -> falls back to the single
    ``SEARCH_BACKEND`` (back-compat). Backends that cannot be built (missing
    key) are SKIPPED with a warning so a partially-configured chain still works
    with whatever providers are available. ``searxng_url`` overrides the SearXNG
    backend URL (the live auto-started instance).
    """
    backends: list[SearchBackend] = []
    for name in chain_backend_names():
        try:
            backends.append(_make_backend(name, searxng_url))
        except ValueError as exc:
            logger.warning(f"Skipping search backend {name!r}: {exc}")
    return backends


def _search_result_is_empty(payload: str) -> bool:
    """A search result JSON string counts as empty (advance the chain) when it
    is an error envelope or carries no results."""
    try:
        data = json.loads(payload)
    except (json.JSONDecodeError, TypeError):
        return True
    if not isinstance(data, dict):
        return True
    if data.get("error"):
        return True
    return not data.get("results")


async def run_search_chain(
    query: str,
    max_results: int = 10,
    time_range=None,
    language=None,
    include_domains=None,
    exclude_domains=None,
    categories="general",
    searxng_url: str | None = None,
) -> str:
    """Run the SEARCH_BACKENDS chain with runtime fallback.

    Tries each backend in order; on a raised error OR an empty/error result it
    advances to the next, returning the first non-empty result (the shared
    ``mcp_core.chains.run_with_fallback`` primitive). Returns an empty-results
    envelope when every backend is exhausted. ``searxng_url`` is the live
    auto-started SearXNG URL (when SearXNG is in the chain).
    """
    backends = search_backends_from_env(searxng_url)
    if not backends:
        requested = chain_backend_names()
        msg = (
            f"Search backends {requested} are missing API keys; configure a key or add searxng"
            if requested
            else "No search backend configured"
        )
        return json.dumps(
            {"results": [], "total": 0, "query": query, "error": msg},
            ensure_ascii=False,
        )
    thunks = [
        (
            lambda b=b: b.search(
                query=query,
                max_results=max_results,
                time_range=time_range,
                language=language,
                include_domains=include_domains,
                exclude_domains=exclude_domains,
                categories=categories,
            )
        )
        for b in backends
    ]
    result = await run_with_fallback(
        thunks,
        is_empty=_search_result_is_empty,
        on_error=lambda idx, exc: logger.warning(
            f"Search backend #{idx} raised: {type(exc).__name__}"
        ),
    )
    if result is None:
        return json.dumps(
            {"results": [], "total": 0, "query": query}, ensure_ascii=False
        )
    return result


__all__ = [
    "BraveBackend",
    "ExaBackend",
    "SearchBackend",
    "SearxngBackend",
    "TavilyBackend",
    "chain_backend_names",
    "run_search_chain",
    "search_backend_from_env",
    "search_backends_from_env",
]
