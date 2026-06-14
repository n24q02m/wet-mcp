import json
import unittest.mock

import pytest

from wet_mcp.sources.search_backends import (
    SearxngBackend,
    TavilyBackend,
    search_backend_from_env,
)


async def test_tavily_maps_rest_response():
    with unittest.mock.patch("httpx.AsyncClient.post") as post:
        resp = unittest.mock.AsyncMock()
        resp.status_code = 200
        resp.json = unittest.mock.Mock(
            return_value={
                "results": [{"url": "https://e/1", "title": "R1", "content": "c1"}]
            }
        )
        post.return_value = resp
        out = json.loads(await TavilyBackend("k").search("q", max_results=1))
        assert out["total"] == 1
        assert out["query"] == "q"
        assert out["results"][0]["url"] == "https://e/1"
        assert "snippet" in out["results"][0]


async def test_tavily_http_error_returns_error_json():
    with unittest.mock.patch("httpx.AsyncClient.post") as post:
        resp = unittest.mock.AsyncMock()
        resp.status_code = 401
        post.return_value = resp
        out = json.loads(await TavilyBackend("bad").search("q"))
        assert "error" in out


def test_factory_defaults_to_searxng(monkeypatch):
    monkeypatch.delenv("SEARCH_BACKEND", raising=False)
    assert isinstance(search_backend_from_env(), SearxngBackend)


def test_factory_tavily_requires_key(monkeypatch):
    monkeypatch.setenv("SEARCH_BACKEND", "tavily")
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    with pytest.raises(ValueError, match="TAVILY_API_KEY"):
        search_backend_from_env()


async def test_server_search_routes_through_backend(monkeypatch):
    monkeypatch.setenv("SEARCH_BACKEND", "searxng")
    fake = unittest.mock.AsyncMock()
    fake.search = unittest.mock.AsyncMock(
        return_value='{"results": [], "total": 0, "query": "q"}'
    )
    with unittest.mock.patch(
        "wet_mcp.sources.search_backends.search_backend_from_env", return_value=fake
    ):
        from wet_mcp.server import search

        result = await search(action="search", query="python tutorial", max_results=5)
        assert "results" in result
        fake.search.assert_awaited()
