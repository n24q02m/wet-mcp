"""Multi-user LLM availability gates + per-request embed/rerank backend.

Audit-confirmed bugs (single-user healthy; do not regress):

1. Anthropic gate drift — the relay offers ANTHROPIC_API_KEY and suggests
   ``anthropic/claude-*`` but the LLM availability gates excluded Anthropic,
   so an Anthropic-only user could never run ``extract(action=agent)`` /
   ``media(action=analyze)`` even though litellm passthrough supports it.

2. Multi-user LLM gates read ``os.getenv`` — per-sub keys are never in
   ``os.environ`` (they live in the per-sub PerPluginStore bucket), so the
   gate must consult ``credentials_for_current_request()`` instead, or the
   LLM features are permanently broken for every remote user.

3. Embedding/rerank backend was a process-global singleton fixed at startup
   from process env, so in multi-user a sub who submits a cloud embed/rerank
   key still got LOCAL ONNX. The per-request resolver must build a per-sub
   ``CloudEmbeddingBackend`` / ``CloudReranker`` (never rebinding the module
   singleton), and a second sub must NOT see the first sub's key/chain.

CRITICAL multi-user invariant: per-sub creds NEVER touch the process-global
``os.environ``; they flow request-scoped via ``credentials_for_current_request``
/ ``api_key_for_model`` bound to the per-request ``_current_sub`` contextvar.
"""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from wet_mcp.credential_state import (
    CLOUD_KEYS,
    set_current_sub,
    store_for_sub,
)


@pytest.fixture(autouse=True)
def _isolate(monkeypatch, tmp_path):
    """Each test: sub=None, no CLOUD_KEYS / *_MODELS chains in env, fresh store."""
    monkeypatch.setenv("WET_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CREDENTIAL_SECRET", "s")
    set_current_sub(None)
    for k in (*CLOUD_KEYS, "ANTHROPIC_API_KEY", "GOOGLE_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    for k in ("EMBEDDING_MODELS", "RERANK_MODELS", "LLM_MODELS", "PUBLIC_URL"):
        monkeypatch.delenv(k, raising=False)
    yield
    set_current_sub(None)


# ---------------------------------------------------------------------------
# Bug 1: Anthropic gate drift (single-user)
# ---------------------------------------------------------------------------


class TestAnthropicGateDriftSingleUser:
    def test_detect_llm_provider_recognises_anthropic(self, monkeypatch):
        from wet_mcp.sources import agent_orchestrator as ao

        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-x")
        assert ao.detect_llm_provider() == "ANTHROPIC_API_KEY"

    def test_has_llm_provider_recognises_anthropic(self, monkeypatch):
        from wet_mcp import llm

        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-x")
        assert llm._has_llm_provider() is True

    async def test_run_agent_does_not_bail_with_anthropic_only(self, monkeypatch):
        """An Anthropic-only single-user must clear the no-provider gate."""
        from wet_mcp.sources import agent_orchestrator as ao

        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-x")
        # detect_llm_provider must be non-None so run_agent proceeds past the gate.
        assert ao.detect_llm_provider() is not None


# ---------------------------------------------------------------------------
# Bug 2: multi-user LLM gates must be sub-aware (not os.getenv)
# ---------------------------------------------------------------------------


class TestMultiUserLlmGate:
    def test_detect_llm_provider_reads_per_sub_bucket(self, monkeypatch):
        from wet_mcp.sources import agent_orchestrator as ao

        store_for_sub("user_a", {"GEMINI_API_KEY": "gem_a"})
        # No keys in os.environ at all (cleared by fixture).
        set_current_sub("user_a")
        assert ao.detect_llm_provider() == "GEMINI_API_KEY"

    def test_detect_llm_provider_per_sub_anthropic(self, monkeypatch):
        from wet_mcp.sources import agent_orchestrator as ao

        store_for_sub("user_a", {"ANTHROPIC_API_KEY": "sk-ant-a"})
        set_current_sub("user_a")
        assert ao.detect_llm_provider() == "ANTHROPIC_API_KEY"

    def test_has_llm_provider_reads_per_sub_bucket(self, monkeypatch):
        from wet_mcp import llm

        store_for_sub("user_a", {"OPENAI_API_KEY": "oai_a"})
        set_current_sub("user_a")
        assert llm._has_llm_provider() is True

    def test_gate_does_not_bleed_across_subs(self, monkeypatch):
        """User B with no LLM key must NOT see user A's key via the gate."""
        from wet_mcp import llm
        from wet_mcp.sources import agent_orchestrator as ao

        store_for_sub("user_a", {"GEMINI_API_KEY": "gem_a"})
        store_for_sub("user_b", {"JINA_AI_API_KEY": "jina_b"})  # embed-only, no LLM

        set_current_sub("user_a")
        assert ao.detect_llm_provider() == "GEMINI_API_KEY"
        assert llm._has_llm_provider() is True

        set_current_sub("user_b")
        # Jina is an embedding/rerank provider, not an LLM provider -> no LLM.
        assert ao.detect_llm_provider() is None
        assert llm._has_llm_provider() is False

    def test_gate_false_when_sub_has_no_keys(self):
        from wet_mcp import llm
        from wet_mcp.sources import agent_orchestrator as ao

        store_for_sub("empty_user", {})
        set_current_sub("empty_user")
        assert ao.detect_llm_provider() is None
        assert llm._has_llm_provider() is False


# ---------------------------------------------------------------------------
# Bug 3: per-request embed/rerank backend resolution (multi-user)
# ---------------------------------------------------------------------------


class TestPerRequestEmbedBackend:
    def test_single_user_returns_startup_singleton(self, monkeypatch):
        """sub=None -> the module-level startup singleton, unchanged."""
        from wet_mcp import embedder
        from wet_mcp.embedder import (
            LocalEmbeddingBackend,
            resolve_embed_backend_for_request,
        )

        sentinel = LocalEmbeddingBackend()
        monkeypatch.setattr(embedder, "_backend", sentinel)
        assert resolve_embed_backend_for_request() is sentinel

    def test_multi_user_cloud_key_builds_cloud_backend(self, monkeypatch):
        """sub with a cloud embed chain+key -> a per-request CloudEmbeddingBackend."""
        from wet_mcp.embedder import (
            CloudEmbeddingBackend,
            resolve_embed_backend_for_request,
        )

        store_for_sub(
            "user_a",
            {
                "EMBEDDING_MODELS": "jina_ai/jina-embeddings-v5-text-small",
                "JINA_AI_API_KEY": "jina_a",
            },
        )
        set_current_sub("user_a")
        backend = resolve_embed_backend_for_request()
        assert isinstance(backend, CloudEmbeddingBackend)
        assert backend.model == "jina_ai/jina-embeddings-v5-text-small"

    def test_multi_user_default_chain_with_key_builds_cloud(self, monkeypatch):
        """No explicit chain but a provider key -> the key-gated default cloud model."""
        from wet_mcp.embedder import (
            CloudEmbeddingBackend,
            resolve_embed_backend_for_request,
        )

        store_for_sub("user_a", {"JINA_AI_API_KEY": "jina_a"})
        set_current_sub("user_a")
        backend = resolve_embed_backend_for_request()
        assert isinstance(backend, CloudEmbeddingBackend)
        # jina is first in the default chain -> picked when its key is present.
        assert "jina" in backend.model.lower()

    def test_multi_user_no_cloud_key_uses_local(self, monkeypatch):
        """sub with no embed provider key -> shared local ONNX (not cloud)."""
        from wet_mcp.embedder import (
            CloudEmbeddingBackend,
            resolve_embed_backend_for_request,
        )

        store_for_sub("user_a", {"GITHUB_TOKEN": "ghp_x"})  # no embed provider key
        set_current_sub("user_a")
        backend = resolve_embed_backend_for_request()
        assert not isinstance(backend, CloudEmbeddingBackend)

    def test_multi_user_does_not_rebind_singleton(self, monkeypatch):
        """Resolving a per-sub cloud backend must NOT mutate the module singleton."""
        from wet_mcp import embedder
        from wet_mcp.embedder import (
            LocalEmbeddingBackend,
            resolve_embed_backend_for_request,
        )

        startup = LocalEmbeddingBackend()
        monkeypatch.setattr(embedder, "_backend", startup)

        store_for_sub(
            "user_a",
            {
                "EMBEDDING_MODELS": "jina_ai/jina-embeddings-v5-text-small",
                "JINA_AI_API_KEY": "jina_a",
            },
        )
        set_current_sub("user_a")
        resolve_embed_backend_for_request()
        # Module singleton stays the startup local backend (no cross-sub contamination).
        assert embedder.get_backend() is startup

    def test_second_sub_does_not_see_first_sub_chain(self, monkeypatch):
        """The headline isolation test: sub B must NOT inherit sub A's cloud chain."""
        from wet_mcp.embedder import (
            CloudEmbeddingBackend,
            resolve_embed_backend_for_request,
        )

        store_for_sub(
            "user_a",
            {
                "EMBEDDING_MODELS": "gemini/gemini-embedding-001",
                "GEMINI_API_KEY": "gem_a",
            },
        )
        store_for_sub("user_b", {})  # nothing configured

        set_current_sub("user_a")
        a_backend = resolve_embed_backend_for_request()
        assert isinstance(a_backend, CloudEmbeddingBackend)
        assert a_backend.model == "gemini/gemini-embedding-001"

        set_current_sub("user_b")
        b_backend = resolve_embed_backend_for_request()
        # User B has no cloud key/chain -> local ONNX, NOT A's gemini cloud model.
        assert not isinstance(b_backend, CloudEmbeddingBackend)


class TestPerRequestRerankBackend:
    def test_single_user_returns_startup_singleton(self, monkeypatch):
        from wet_mcp import reranker
        from wet_mcp.reranker import (
            LocalReranker,
            resolve_rerank_backend_for_request,
        )

        sentinel = LocalReranker()
        monkeypatch.setattr(reranker, "_backend", sentinel)
        assert resolve_rerank_backend_for_request() is sentinel

    def test_multi_user_cloud_key_builds_cloud_reranker(self, monkeypatch):
        from wet_mcp.reranker import (
            CloudReranker,
            resolve_rerank_backend_for_request,
        )

        store_for_sub(
            "user_a",
            {
                "RERANK_MODELS": "cohere/rerank-v3.5",
                "COHERE_API_KEY": "co_a",
            },
        )
        set_current_sub("user_a")
        backend = resolve_rerank_backend_for_request()
        assert isinstance(backend, CloudReranker)
        assert backend.model == "cohere/rerank-v3.5"

    def test_multi_user_no_cloud_key_uses_local(self, monkeypatch):
        from wet_mcp.reranker import (
            CloudReranker,
            resolve_rerank_backend_for_request,
        )

        store_for_sub("user_a", {"GITHUB_TOKEN": "ghp_x"})
        set_current_sub("user_a")
        backend = resolve_rerank_backend_for_request()
        assert not isinstance(backend, CloudReranker)

    def test_second_sub_does_not_see_first_sub_rerank_key(self, monkeypatch):
        from wet_mcp.reranker import (
            CloudReranker,
            resolve_rerank_backend_for_request,
        )

        store_for_sub(
            "user_a",
            {"RERANK_MODELS": "cohere/rerank-v3.5", "COHERE_API_KEY": "co_a"},
        )
        store_for_sub("user_b", {})

        set_current_sub("user_a")
        assert isinstance(resolve_rerank_backend_for_request(), CloudReranker)

        set_current_sub("user_b")
        assert not isinstance(resolve_rerank_backend_for_request(), CloudReranker)

    def test_multi_user_does_not_rebind_singleton(self, monkeypatch):
        from wet_mcp import reranker
        from wet_mcp.reranker import (
            LocalReranker,
            resolve_rerank_backend_for_request,
        )

        startup = LocalReranker()
        monkeypatch.setattr(reranker, "_backend", startup)

        store_for_sub(
            "user_a",
            {"RERANK_MODELS": "cohere/rerank-v3.5", "COHERE_API_KEY": "co_a"},
        )
        set_current_sub("user_a")
        resolve_rerank_backend_for_request()
        assert reranker.get_reranker() is startup


class TestPerRequestBackendForwardsKey:
    """The per-request cloud backend forwards the per-sub key to litellm."""

    async def test_embed_backend_uses_per_sub_key(self, monkeypatch):
        from wet_mcp.embedder import resolve_embed_backend_for_request

        store_for_sub(
            "user_a",
            {
                "EMBEDDING_MODELS": "jina_ai/jina-embeddings-v5-text-small",
                "JINA_AI_API_KEY": "jina_a",
            },
        )

        captured: dict = {}

        async def fake_aembedding(**kwargs):
            captured.update(kwargs)

            class _R:
                data = [{"index": 0, "embedding": [0.1, 0.2]}]

            return _R()

        monkeypatch.setattr("mcp_core.llm.aembedding", fake_aembedding)
        set_current_sub("user_a")
        backend = resolve_embed_backend_for_request()
        await backend.embed_single("hello")
        assert captured["api_key"] == "jina_a"

    def test_rerank_backend_uses_per_sub_key(self, monkeypatch):
        from wet_mcp.reranker import resolve_rerank_backend_for_request

        store_for_sub(
            "user_a",
            {"RERANK_MODELS": "cohere/rerank-v3.5", "COHERE_API_KEY": "co_a"},
        )

        captured: dict = {}

        def fake_rerank(**kwargs):
            captured.update(kwargs)

            class _R:
                results = [{"index": 0, "relevance_score": 0.9}]

            return _R()

        monkeypatch.setattr("mcp_core.llm.rerank", fake_rerank)
        set_current_sub("user_a")
        backend = resolve_rerank_backend_for_request()
        backend.rerank("q", ["doc"], top_n=1)
        assert captured["api_key"] == "co_a"


class TestLiveDispatchWiring:
    """The server dispatch helpers resolve the backend PER REQUEST.

    Guards against regressing the wiring back to the module-level singleton
    (the original bug): ``_embed`` / ``_embed_batch`` / ``_rerank_results``
    must consult the per-request resolver so a sub's cloud key actually takes
    effect at call time.
    """

    async def test_embed_uses_per_sub_cloud_backend(self, monkeypatch):
        from wet_mcp import server

        store_for_sub(
            "user_a",
            {
                "EMBEDDING_MODELS": "jina_ai/jina-embeddings-v5-text-small",
                "JINA_AI_API_KEY": "jina_a",
            },
        )

        captured: dict = {}

        async def fake_aembedding(**kwargs):
            captured.update(kwargs)

            class _R:
                data = [{"index": 0, "embedding": [0.1] * 768}]

            return _R()

        monkeypatch.setattr("mcp_core.llm.aembedding", fake_aembedding)
        set_current_sub("user_a")
        vec = await server._embed("hello")
        assert vec is not None
        # The live dispatch forwarded user_a's per-sub key (not os.environ).
        assert captured["api_key"] == "jina_a"
        assert captured["model"] == "jina_ai/jina-embeddings-v5-text-small"

    async def test_rerank_results_uses_per_sub_cloud_backend(self, monkeypatch):
        from wet_mcp import server

        store_for_sub(
            "user_a",
            {"RERANK_MODELS": "cohere/rerank-v3.5", "COHERE_API_KEY": "co_a"},
        )

        captured: dict = {}

        def fake_rerank(**kwargs):
            captured.update(kwargs)

            class _R:
                results = [
                    {"index": 1, "relevance_score": 0.9},
                    {"index": 0, "relevance_score": 0.1},
                ]

            return _R()

        monkeypatch.setattr("mcp_core.llm.rerank", fake_rerank)
        set_current_sub("user_a")
        results = [{"content": "doc-a"}, {"content": "doc-b"}]
        ranked = await server._rerank_results("q", results, top_n=1)
        assert captured["api_key"] == "co_a"
        # top result is index 1 (doc-b) per the fake scores.
        assert ranked[0]["content"] == "doc-b"

    async def test_rerank_applies_semantic_order_when_candidates_equal_top_n(
        self, monkeypatch
    ):
        """Candidate-count equality must not bypass an available cloud reranker."""
        from wet_mcp import server

        store_for_sub(
            "user_a",
            {"RERANK_MODELS": "cohere/rerank-v3.5", "COHERE_API_KEY": "co_a"},
        )
        captured: dict = {}

        def fake_rerank(**kwargs):
            captured.update(kwargs)

            class _R:
                results = [
                    {"index": 1, "relevance_score": 0.9},
                    {"index": 0, "relevance_score": 0.1},
                ]

            return _R()

        monkeypatch.setattr("mcp_core.llm.rerank", fake_rerank)
        set_current_sub("user_a")
        results = [
            {"content": "keyword-first"},
            {"content": "semantic-first"},
        ]

        ranked = await server._rerank_results("semantic query", results, top_n=2)

        assert [result["content"] for result in ranked] == [
            "semantic-first",
            "keyword-first",
        ]
        assert captured["top_n"] == 2

    async def test_web_search_reranks_only_structurally_usable_results(
        self, monkeypatch
    ):
        """Web search fills top_n from usable results regardless of score scale."""
        from wet_mcp import server

        store_for_sub(
            "user_a",
            {"RERANK_MODELS": "cohere/rerank-v3.5", "COHERE_API_KEY": "co_a"},
        )

        def fake_rerank(**kwargs):
            relevance_by_document = {
                "\t": 0.99,
                "Best semantic result.": 0.19,
                "Second-best semantic result.": 0.05,
                "A less relevant candidate.": 0.01,
            }
            ranked = sorted(
                enumerate(kwargs["documents"]),
                key=lambda item: relevance_by_document[item[1]],
                reverse=True,
            )[: kwargs["top_n"]]

            class _R:
                results = [
                    {
                        "index": index,
                        "relevance_score": relevance_by_document[document],
                    }
                    for index, document in ranked
                ]

            return _R()

        async def fake_search_chain(**_kwargs):
            return json.dumps(
                {
                    "results": [
                        {
                            "title": "semantic-second-low-score",
                            "url": "https://example.com/second",
                            "snippet": "Second-best semantic result.",
                        },
                        {
                            "title": "empty-structural-result",
                            "url": "https://account.apple.com/",
                            "snippet": "",
                            "content": "\t",
                        },
                        {
                            "title": "not-selected",
                            "url": "https://example.com/other",
                            "snippet": "A less relevant candidate.",
                        },
                        {
                            "title": "semantic-best-low-score",
                            "url": "https://example.com/best",
                            "snippet": "Best semantic result.",
                        },
                    ],
                    "total": 4,
                }
            )

        async def fake_ensure_searxng():
            return "http://searxng.test"

        monkeypatch.setattr("mcp_core.llm.rerank", fake_rerank)
        monkeypatch.setattr(server, "_require_credentials", lambda: None)
        monkeypatch.setattr(server, "is_uvx_tool_venv", lambda: False)
        monkeypatch.setattr(server, "_web_cache", None)
        monkeypatch.setattr(server, "ensure_searxng", fake_ensure_searxng)
        monkeypatch.setattr(
            server.search_backends, "chain_backend_names", lambda: ["searxng"]
        )
        monkeypatch.setattr(
            server.search_backends, "run_search_chain", fake_search_chain
        )
        set_current_sub("user_a")

        response = await server.search("search", query="semantic query", max_results=2)
        results = response.structuredContent["results"]

        assert [result["title"] for result in results] == [
            "semantic-best-low-score",
            "semantic-second-low-score",
        ]
        assert [result["score"] for result in results] == [0.19, 0.05]
        assert response.structuredContent["total"] == 2

    async def test_single_user_embed_unchanged(self, monkeypatch):
        """sub=None still uses the startup singleton (no behaviour change)."""
        from wet_mcp import embedder, server

        calls: list[str] = []

        class _FakeBackend:
            async def embed_single(self, text, dims=None):
                calls.append(text)
                return [0.5] * 4

        monkeypatch.setattr(embedder, "_backend", _FakeBackend())
        set_current_sub(None)
        vec = await server._embed("hi")
        assert vec == [0.5] * 4
        assert calls == ["hi"]


async def test_completion_uses_each_subject_model_endpoint_and_key(monkeypatch):
    from wet_mcp.config import settings
    from wet_mcp.credential_state import has_llm_provider
    from wet_mcp.sources.agent_orchestrator import _llm_synthesize

    model = "openrouter/minimax/minimax-m3:free"
    monkeypatch.setenv("PUBLIC_URL", "https://wet.example.com")
    monkeypatch.setattr(settings, "llm_models", "openai/operator-model")
    monkeypatch.setenv("OPENROUTER_API_KEY", "operator-key")
    for subject in ("a", "b"):
        store_for_sub(
            subject,
            {
                "LLM_MODELS": model,
                "LLM_API_BASE": f"https://gateway.example/{subject}/openrouter/v1",
                "OPENROUTER_API_KEY": f"subject-{subject}",
            },
        )

    async def provider(**kwargs):
        subject = kwargs["api_key"].removeprefix("subject-")
        assert subject in ("a", "b")
        assert kwargs["model"] == model
        assert kwargs["api_base"] == f"https://gateway.example/{subject}/openrouter/v1"
        await asyncio.sleep(0)
        return SimpleNamespace(
            choices=[
                SimpleNamespace(message=SimpleNamespace(content=f"answer-{subject}"))
            ]
        )

    monkeypatch.setattr("mcp_core.llm.acompletion", provider)

    async def synthesize(subject):
        set_current_sub(subject)
        assert has_llm_provider()
        return await _llm_synthesize("Summarize the cited fixture.", None)

    assert await asyncio.gather(synthesize("a"), synthesize("b")) == [
        "answer-a",
        "answer-b",
    ]


async def test_missing_subject_key_cannot_spend_operator_key(monkeypatch):
    from wet_mcp.llm import acompletion

    monkeypatch.setenv("OPENROUTER_API_KEY", "operator-key")
    store_for_sub(
        "unconfigured",
        {"LLM_MODELS": "openrouter/minimax/minimax-m3:free"},
    )
    set_current_sub("unconfigured")
    provider = AsyncMock()
    monkeypatch.setattr("mcp_core.llm.acompletion", provider)

    with pytest.raises(RuntimeError, match="not configured for this subject"):
        await acompletion(
            model="openrouter/minimax/minimax-m3:free",
            messages=[{"role": "user", "content": "fixture"}],
        )
    provider.assert_not_awaited()


def test_hosted_request_without_subject_has_no_operator_configuration(monkeypatch):
    from wet_mcp.config import settings
    from wet_mcp.credential_state import (
        credentials_for_current_request,
        has_llm_provider,
    )
    from wet_mcp.llm import get_llm_config
    from wet_mcp.sources.search_backends import chain_backend_names

    monkeypatch.setenv("PUBLIC_URL", "https://wet.example.com")
    monkeypatch.setenv("OPENROUTER_API_KEY", "operator-key")
    monkeypatch.setattr(settings, "llm_models", "openrouter/minimax/minimax-m3:free")
    monkeypatch.setenv("SEARCH_BACKENDS", "tavily")
    monkeypatch.setenv("TAVILY_API_KEY", "operator-key")
    assert credentials_for_current_request() == {}
    assert not has_llm_provider()
    assert get_llm_config()["model"] is None
    assert chain_backend_names() == []


async def test_search_provider_keys_and_cache_are_subject_isolated(
    monkeypatch, tmp_path
):
    import httpx

    from wet_mcp import server
    from wet_mcp.cache import WebCache
    from wet_mcp.config import settings

    monkeypatch.setenv("PUBLIC_URL", "https://wet.example.com")
    monkeypatch.setenv("SEARCH_BACKENDS", "brave")
    monkeypatch.setenv("BRAVE_API_KEY", "operator-key")
    monkeypatch.setenv("TAVILY_API_KEY", "operator-key")
    monkeypatch.setattr(settings, "wet_search_budget", 0)
    for subject in ("a", "b"):
        store_for_sub(
            subject,
            {"SEARCH_BACKENDS": "tavily", "TAVILY_API_KEY": f"subject-{subject}"},
        )
    requested_keys = []

    async def post(_client, url, *, json):
        assert url == "https://api.tavily.com/search"
        key = json["api_key"]
        assert key in ("subject-a", "subject-b")
        requested_keys.append(key)
        await asyncio.sleep(0)
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "url": f"https://example.com/{key}",
                        "title": key,
                        "content": "Subject-specific search fixture with useful context.",
                    }
                ],
            },
        )

    monkeypatch.setattr(httpx.AsyncClient, "post", post)
    monkeypatch.setattr(
        httpx.AsyncClient,
        "get",
        AsyncMock(side_effect=AssertionError("unexpected provider")),
    )
    monkeypatch.setattr(server, "_require_credentials", lambda: None)
    monkeypatch.setattr(server, "is_uvx_tool_venv", lambda: False)
    monkeypatch.setattr(
        "wet_mcp.reranker.resolve_rerank_backend_for_request", lambda: None
    )
    monkeypatch.setattr(server, "_backend_init_task", None)
    cache = WebCache(tmp_path / "search-cache.db")
    monkeypatch.setattr(server, "_web_cache", cache)

    async def search_as(subject, query):
        set_current_sub(subject)
        response = await server.search("search", query=query, max_results=1)
        return response.structuredContent["results"][0]["title"]

    try:
        assert await asyncio.gather(
            search_as("a", "concurrent fixture"),
            search_as("b", "concurrent fixture"),
        ) == ["subject-a", "subject-b"]
        assert await search_as("a", "cached fixture") == "subject-a"
        assert await search_as("b", "cached fixture") == "subject-b"
        assert await search_as("a", "cached fixture") == "subject-a"
        assert requested_keys.count("subject-a") == 2
        assert requested_keys.count("subject-b") == 2
    finally:
        cache.close()


async def test_search_missing_subject_key_never_uses_operator_key(monkeypatch):
    from wet_mcp.sources.search_backends import run_search_chain

    monkeypatch.setenv("TAVILY_API_KEY", "operator-key")
    store_for_sub("unconfigured", {"SEARCH_BACKENDS": "tavily"})
    set_current_sub("unconfigured")
    provider = AsyncMock(side_effect=AssertionError("operator spend attempted"))
    monkeypatch.setattr("httpx.AsyncClient.post", provider)
    result = json.loads(await run_search_chain("fixture"))
    assert result["search_backend"]["attempted"] == []
    assert result["search_backend"]["selected"] is None
    assert result["error"]
    provider.assert_not_awaited()


async def test_hosted_searxng_is_ssrf_vetted_without_operator_auth_or_restart(
    monkeypatch,
):
    from web_core.search import SearchResult

    from wet_mcp.sources import searxng
    from wet_mcp.sources.search_backends import run_search_chain

    monkeypatch.setenv("PUBLIC_URL", "https://wet.example.com")
    monkeypatch.setattr(searxng.settings, "searxng_auth_user", "operator-user")
    monkeypatch.setattr(searxng.settings, "searxng_auth_pass", "operator-pass")
    store_for_sub(
        "reader",
        {
            "SEARCH_BACKENDS": "searxng",
            "SEARXNG_URL": "https://search.example",
        },
    )
    set_current_sub("reader")

    checked_urls = []
    monkeypatch.setattr(
        searxng,
        "is_safe_url",
        lambda url: checked_urls.append(url) or True,
        raising=False,
    )
    monkeypatch.setattr(searxng, "_check_health", AsyncMock(return_value=False))
    restart = AsyncMock(return_value="http://localhost:41592")
    monkeypatch.setattr("wet_mcp.searxng_runner.ensure_searxng", restart)
    provider = AsyncMock(
        return_value=[
            SearchResult(
                url="https://result.example",
                title="Fixture",
                snippet="Hosted SearXNG result",
                source="fixture",
            )
        ]
    )
    monkeypatch.setattr(searxng, "_wc_search", provider)

    result = json.loads(await run_search_chain("fixture", max_results=1))

    assert result["results"][0]["title"] == "Fixture"
    assert checked_urls == ["https://search.example"]
    restart.assert_not_awaited()
    assert provider.await_args.kwargs["auth"] is None


async def test_hosted_searxng_rejects_unsafe_subject_url_before_network(
    monkeypatch,
):
    from wet_mcp.sources import searxng
    from wet_mcp.sources.search_backends import run_search_chain

    monkeypatch.setenv("PUBLIC_URL", "https://wet.example.com")
    store_for_sub(
        "reader",
        {
            "SEARCH_BACKENDS": "searxng",
            "SEARXNG_URL": "http://127.0.0.1:8080",
        },
    )
    set_current_sub("reader")

    checked_urls = []
    monkeypatch.setattr(
        searxng,
        "is_safe_url",
        lambda url: checked_urls.append(url) or False,
        raising=False,
    )
    health = AsyncMock(side_effect=AssertionError("unsafe network request attempted"))
    provider = AsyncMock(
        side_effect=AssertionError("unsafe provider request attempted")
    )
    monkeypatch.setattr(searxng, "_check_health", health)
    monkeypatch.setattr(searxng, "_wc_search", provider)

    result = json.loads(await run_search_chain("fixture"))

    assert result["search_backend"]["selected"] is None
    assert checked_urls == ["http://127.0.0.1:8080"]
    health.assert_not_awaited()
    provider.assert_not_awaited()


async def test_query_expansion_uses_subject_completion_without_operator_keys(
    monkeypatch,
):
    from wet_mcp.sources.search_strategies import expand_query

    store_for_sub(
        "expander",
        {
            "LLM_MODELS": "openrouter/minimax/minimax-m3:free",
            "OPENROUTER_API_KEY": "subject-key",
        },
    )
    set_current_sub("expander")
    provider = AsyncMock(
        return_value=SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content="async cancellation\nasync task lifecycle"
                    )
                )
            ],
        )
    )
    monkeypatch.setattr("mcp_core.llm.acompletion", provider)
    assert await expand_query("async tasks") == [
        "async tasks",
        "async cancellation",
        "async task lifecycle",
    ]
    assert provider.await_args.kwargs["model"] == "openrouter/minimax/minimax-m3:free"
    assert provider.await_args.kwargs["api_key"] == "subject-key"


@pytest.mark.parametrize(
    "action", ["research", "similar", "docs-discovery", "docs-fallback"]
)
async def test_auxiliary_search_paths_use_subject_chain(action, monkeypatch):
    import httpx

    from wet_mcp import server
    from wet_mcp.config import settings

    monkeypatch.setenv("PUBLIC_URL", "https://wet.example.com")
    monkeypatch.setenv("SEARCH_BACKENDS", "searxng")
    monkeypatch.setattr(settings, "wet_search_budget", 0)
    store_for_sub(
        "reader", {"SEARCH_BACKENDS": "tavily", "TAVILY_API_KEY": "subject-key"}
    )
    set_current_sub("reader")
    forbidden = AsyncMock(side_effect=AssertionError("personal SearXNG path reached"))
    monkeypatch.setattr(server, "ensure_searxng", forbidden)
    monkeypatch.setattr("wet_mcp.searxng_runner.ensure_searxng", forbidden)
    monkeypatch.setattr("wet_mcp.sources.searxng.search", forbidden)
    monkeypatch.setattr(server, "_require_credentials", lambda: None)
    monkeypatch.setattr(server, "is_uvx_tool_venv", lambda: False)
    monkeypatch.setattr(server, "_web_cache", None)
    monkeypatch.setattr(server, "_backend_init_task", None)
    monkeypatch.setattr(
        "wet_mcp.reranker.resolve_rerank_backend_for_request", lambda: None
    )
    monkeypatch.setattr(
        "wet_mcp.sources.docs.discover_library", AsyncMock(return_value=None)
    )
    monkeypatch.setattr(
        "wet_mcp.sources.search_strategies.raw_extract",
        AsyncMock(
            return_value=json.dumps(
                [{"title": "source fixture", "content": "fixture text"}]
            )
        ),
    )
    provider = AsyncMock(
        return_value=httpx.Response(
            200,
            json={
                "results": [
                    {
                        "url": "https://fixture.example/docs",
                        "title": "fixture-result",
                        "content": "Useful configured-chain documentation.",
                    }
                ]
            },
        )
    )
    monkeypatch.setattr(httpx.AsyncClient, "post", provider)

    if action == "docs-discovery":
        docs_url, _, _, _ = await server._discover_docs_url("fixture", "python")
        assert docs_url == "https://fixture.example/docs"
    elif action == "docs-fallback":
        result = await server._do_immediate_fallback_search(
            "https://source.example/docs", "fixture", "python", "routing", 1
        )
        assert result["results"][0]["title"] == "fixture-result"
    else:
        query = (
            "https://source.example/docs" if action == "similar" else "fixture research"
        )
        response = await server.search(action, query=query, max_results=1)
        assert response.structuredContent["results"][0]["title"] == "fixture-result"
    assert provider.await_args.kwargs["json"]["api_key"] == "subject-key"
    forbidden.assert_not_awaited()


def test_subject_without_completion_chain_cannot_infer_a_paid_model():
    from wet_mcp.llm import get_llm_config

    store_for_sub("no-model", {"OPENAI_API_KEY": "subject-key"})
    set_current_sub("no-model")
    assert get_llm_config()["model"] is None
    assert get_llm_config()["fallbacks"] is None
