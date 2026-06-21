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
    for k in ("EMBEDDING_MODELS", "RERANK_MODELS", "LLM_MODELS"):
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
            Qwen3EmbedBackend,
            resolve_embed_backend_for_request,
        )

        sentinel = Qwen3EmbedBackend()
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
            Qwen3EmbedBackend,
            resolve_embed_backend_for_request,
        )

        startup = Qwen3EmbedBackend()
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
            Qwen3Reranker,
            resolve_rerank_backend_for_request,
        )

        sentinel = Qwen3Reranker()
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
            Qwen3Reranker,
            resolve_rerank_backend_for_request,
        )

        startup = Qwen3Reranker()
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
