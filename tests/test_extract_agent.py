"""Tests for ``extract(action="agent")`` orchestration (Phase 3 Task 2)."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest

from wet_mcp.sources import agent_orchestrator as ao


@pytest.fixture(autouse=True)
def _clear_provider_env(monkeypatch):
    """Default to NO LLM provider key set; per-test sets what they need."""
    for key in ao._PROVIDER_KEYS + ("ANTHROPIC_API_KEY",):
        monkeypatch.delenv(key, raising=False)
    yield


@pytest.fixture
def _gemini_env(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")


def _make_search_payload(urls: list[str]) -> str:
    return json.dumps(
        {"results": [{"url": u, "title": f"Title for {u}"} for u in urls]}
    )


def _make_extract_payload(url: str, body: str = "Body content") -> str:
    return json.dumps(
        [
            {
                "url": url,
                "markdown": body,
                "clean_text": body,
                "metadata": {
                    "title": f"Title for {url}",
                    "scrape_strategy_used": "basic_http",
                },
            }
        ]
    )


@pytest.mark.asyncio
async def test_no_provider_returns_structured_error() -> None:
    result = await ao.run_agent(query="anything")
    assert isinstance(result, str)
    assert result.startswith("Error: no LLM provider detected")
    assert "GEMINI_API_KEY" in result


@pytest.mark.asyncio
async def test_empty_query_returns_error(_gemini_env) -> None:
    result = await ao.run_agent(query="   ")
    assert isinstance(result, str)
    assert result.startswith("Error: query is required")


@pytest.mark.asyncio
async def test_pipeline_search_then_extract_then_synthesize(_gemini_env) -> None:
    urls = [f"https://example.com/{i}" for i in range(5)]
    with (
        patch(
            "wet_mcp.sources.searxng.search",
            new_callable=AsyncMock,
            return_value=_make_search_payload(urls),
        ),
        patch(
            "wet_mcp.sources.crawler.extract",
            new_callable=AsyncMock,
            side_effect=lambda urls=(), **_kw: _make_extract_payload(
                (urls or ["https://x"])[0]
            ),
        ),
        patch(
            "wet_mcp.sources.agent_orchestrator._llm_synthesize",
            new_callable=AsyncMock,
            return_value="# Synthesis\n\nFact [1] another [2]. ## Sources\n- [1]\n- [2]",
        ),
    ):
        result = await ao.run_agent(query="explain X", max_urls=5)

    assert isinstance(result, dict)
    assert "markdown" in result
    assert "Synthesis" in result["markdown"]
    assert len(result["sources"]) == 5
    assert result["sources"][0]["index"] == 1
    assert result["sources"][0]["url"] == "https://example.com/0"
    assert len(result["per_url_metadata"]) == 5
    assert result["per_url_metadata"][0]["extract_strategy"] == "basic_http"


@pytest.mark.asyncio
async def test_token_budget_caps_per_extract_size(_gemini_env) -> None:
    huge = "x" * 50000
    extracts = [
        {"url": f"https://e.com/{i}", "markdown": huge, "metadata": {"title": "T"}}
        for i in range(5)
    ]
    prompt = ao.build_cited_prompt("q", extracts, token_budget=10000)
    # token_budget=10000 -> per-extract chars ~ ((10000-200)//5) * 4 = 7840
    assert len(prompt) < 5 * 50000, "per-extract truncation must apply"
    assert "[truncated for token budget]" in prompt


@pytest.mark.asyncio
async def test_max_urls_default_5_cap_20(_gemini_env) -> None:
    # Default
    assert ao._clamp_max_urls(0) == 1
    assert ao._clamp_max_urls(5) == 5
    assert ao._clamp_max_urls(100) == 20
    assert ao._clamp_max_urls(20) == 20


@pytest.mark.asyncio
async def test_synthesis_prompt_includes_numbered_citations(_gemini_env) -> None:
    extracts = [
        {"url": "https://a.com", "markdown": "Alpha", "metadata": {"title": "A"}},
        {"url": "https://b.com", "markdown": "Beta", "metadata": {"title": "B"}},
        {"url": "https://c.com", "markdown": "Gamma", "metadata": {"title": "C"}},
    ]
    prompt = ao.build_cited_prompt("compare", extracts, token_budget=10000)
    assert "[1]" in prompt
    assert "[2]" in prompt
    assert "[3]" in prompt
    assert "https://a.com" in prompt
    assert "Alpha" in prompt
    assert "preserve numeric citation markers" in prompt.lower()


@pytest.mark.asyncio
async def test_search_failure_returns_error_string(_gemini_env) -> None:
    with patch(
        "wet_mcp.sources.searxng.search",
        new_callable=AsyncMock,
        side_effect=RuntimeError("searxng down"),
    ):
        result = await ao.run_agent(query="x")
    assert isinstance(result, str)
    assert "Error: search failed" in result


@pytest.mark.asyncio
async def test_no_search_results_returns_empty_synthesis(_gemini_env) -> None:
    with patch(
        "wet_mcp.sources.searxng.search",
        new_callable=AsyncMock,
        return_value=json.dumps({"results": []}),
    ):
        result = await ao.run_agent(query="obscure")
    assert isinstance(result, dict)
    assert result["sources"] == []
    assert "No results found" in result["markdown"]


@pytest.mark.asyncio
async def test_synthesis_failure_returns_error_string(_gemini_env) -> None:
    urls = ["https://example.com/1"]
    with (
        patch(
            "wet_mcp.sources.searxng.search",
            new_callable=AsyncMock,
            return_value=_make_search_payload(urls),
        ),
        patch(
            "wet_mcp.sources.crawler.extract",
            new_callable=AsyncMock,
            return_value=_make_extract_payload(urls[0]),
        ),
        patch(
            "wet_mcp.sources.agent_orchestrator._llm_synthesize",
            new_callable=AsyncMock,
            side_effect=RuntimeError("api 500"),
        ),
    ):
        result = await ao.run_agent(query="test")
    assert isinstance(result, str)
    assert "Error: synthesis failed" in result


@pytest.mark.asyncio
async def test_extract_error_propagates_to_per_url_metadata(_gemini_env) -> None:
    urls = ["https://broken.com/1"]
    with (
        patch(
            "wet_mcp.sources.searxng.search",
            new_callable=AsyncMock,
            return_value=_make_search_payload(urls),
        ),
        patch(
            "wet_mcp.sources.crawler.extract",
            new_callable=AsyncMock,
            side_effect=RuntimeError("boom"),
        ),
        patch(
            "wet_mcp.sources.agent_orchestrator._llm_synthesize",
            new_callable=AsyncMock,
            return_value="ok",
        ),
    ):
        result = await ao.run_agent(query="test")
    assert isinstance(result, dict)
    assert result["per_url_metadata"][0]["error"] == "boom"


@pytest.mark.asyncio
async def test_provider_detection_priority(_gemini_env, monkeypatch) -> None:
    # Gemini wins when set
    assert ao.detect_llm_provider() == "GEMINI_API_KEY"
    monkeypatch.delenv("GEMINI_API_KEY")
    monkeypatch.setenv("OPENAI_API_KEY", "x")
    assert ao.detect_llm_provider() == "OPENAI_API_KEY"
    monkeypatch.setenv("XAI_API_KEY", "x")
    monkeypatch.delenv("OPENAI_API_KEY")
    assert ao.detect_llm_provider() == "XAI_API_KEY"
    monkeypatch.delenv("XAI_API_KEY")
    monkeypatch.setenv("GOOGLE_API_KEY", "x")
    assert ao.detect_llm_provider() == "GOOGLE_API_KEY"
