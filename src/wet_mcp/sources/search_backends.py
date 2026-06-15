"""Pluggable web-search backends. Default SearXNG (local), Tavily (cloud) for CF
where SearXNG cannot run. All return the same JSON string {results, total, query}
| {error} that server.py's search action already expects from searxng.search().
"""

from __future__ import annotations

import json
import os
from typing import Protocol

import httpx

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


def search_backend_from_env() -> SearchBackend:
    name = (os.getenv("SEARCH_BACKEND", settings.search_backend) or "searxng").lower()
    if name == "tavily":
        key = os.getenv("TAVILY_API_KEY", settings.tavily_api_key)
        if not key:
            raise ValueError(
                "TAVILY_API_KEY env var required for SEARCH_BACKEND=tavily"
            )
        return TavilyBackend(key)
    if name == "searxng":
        return SearxngBackend(settings.searxng_url)
    raise ValueError(f"Unknown SEARCH_BACKEND: {name}")


__all__ = [
    "SearchBackend",
    "SearxngBackend",
    "TavilyBackend",
    "search_backend_from_env",
]
