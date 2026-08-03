"""The per-request embed/rerank resolvers must honour the disable-local flags.

Two backend-selection paths exist and they disagreed. The startup path
(``config.resolve_embedding_backend``) returns ``'unavailable'`` when the cloud
chain is empty and ``DISABLE_LOCAL_EMBED`` is set. The per-request path
(``embedder.resolve_embed_backend_for_request``) fell through to the local ONNX
backend unconditionally, so on a deployment built WITHOUT the local extras --
the http-slim image, which ``Dockerfile`` uninstalls ``qwen3-embed`` and
``onnxruntime`` from -- every indexing request for a sub with no cloud chain
died on ``ModuleNotFoundError: No module named 'qwen3_embed'`` raised from the
lazy import inside ``Qwen3EmbedBackend._get_model``. Live D1 recorded exactly
that in ``index_state='failed'`` (#1614) while ``config status`` reported the
startup singleton and claimed embedding was available.

The expected behaviour is the one the startup path already defines: no cloud
chain + local disabled == gracefully UNAVAILABLE. Not the local backend, and
not the startup singleton either -- that one carries the OPERATOR's key, and
spending it on an arbitrary sub is what the resolver's docstring rules out.

``qwen3_embed`` is installed in the dev venv, so these tests intercept the
import instead of relying on its absence: that both reproduces the slim image
and makes "the local leg was never reached" assertable. A test that only
checked the return value would stay green if the import happened first.
"""

from __future__ import annotations

import builtins

import pytest

from wet_mcp.credential_state import (
    CLOUD_KEYS,
    set_current_sub,
    store_for_sub,
)


@pytest.fixture(autouse=True)
def _isolate(monkeypatch, tmp_path):
    """sub=None, no provider keys / chains in env, fresh per-sub store."""
    monkeypatch.setenv("WET_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CREDENTIAL_SECRET", "s")
    set_current_sub(None)
    for k in (*CLOUD_KEYS, "ANTHROPIC_API_KEY", "GOOGLE_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    for k in ("EMBEDDING_MODELS", "RERANK_MODELS", "LLM_MODELS"):
        monkeypatch.delenv(k, raising=False)

    # The shared local singletons are process-wide; a leftover from another
    # test would make "returns the shared local backend" pass for the wrong
    # reason.
    from wet_mcp import embedder, reranker

    monkeypatch.setattr(embedder, "_shared_local_backend", None)
    monkeypatch.setattr(reranker, "_shared_local_backend", None)
    yield
    set_current_sub(None)


@pytest.fixture
def slim_image(monkeypatch):
    """Make ``qwen3_embed`` unimportable, as the http-slim build leaves it.

    Returns the list of import names the code under test asked for, so a test
    can assert the local leg was never even entered.
    """
    real_import = builtins.__import__
    attempted: list[str] = []

    def _guarded(name, *args, **kwargs):
        if name == "qwen3_embed" or name.startswith("qwen3_embed."):
            attempted.append(name)
            raise ModuleNotFoundError(f"No module named '{name}'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _guarded)
    return attempted


@pytest.fixture
def local_embed_disabled(monkeypatch):
    from wet_mcp.config import settings

    monkeypatch.setattr(settings, "disable_local_embed", True)


@pytest.fixture
def local_rerank_disabled(monkeypatch):
    from wet_mcp.config import settings

    monkeypatch.setattr(settings, "disable_local_rerank", True)


# ---------------------------------------------------------------------------
# Embedding
# ---------------------------------------------------------------------------


class TestEmbedResolverHonoursDisableLocalEmbed:
    def test_no_chain_and_local_disabled_resolves_to_none(self, local_embed_disabled):
        """The exit the slim image actually takes: gracefully unavailable."""
        from wet_mcp.embedder import resolve_embed_backend_for_request

        store_for_sub("user_a", {"GITHUB_TOKEN": "ghp_x"})  # no embed provider key
        set_current_sub("user_a")

        assert resolve_embed_backend_for_request() is None

    async def test_no_chain_and_local_disabled_never_imports_qwen3_embed(
        self, local_embed_disabled, slim_image
    ):
        """End-to-end through the live dispatch helper, on a slim image.

        ``server._embed`` is what the search path calls. With the local leg
        still reachable this raises ModuleNotFoundError out of the lazy import;
        the fix has to make the resolver say "none" BEFORE anything touches
        ``qwen3_embed``, which is why the import list is asserted too.
        """
        from wet_mcp import server

        store_for_sub("user_a", {"GITHUB_TOKEN": "ghp_x"})
        set_current_sub("user_a")

        assert await server._embed("hello", is_query=True) is None
        assert slim_image == [], f"local ONNX leg was entered: {slim_image}"

    async def test_no_chain_and_local_disabled_degrades_the_index_batch(
        self, local_embed_disabled, slim_image
    ):
        """The batch path the background indexer uses degrades the same way."""
        from wet_mcp import server

        store_for_sub("user_a", {"GITHUB_TOKEN": "ghp_x"})
        set_current_sub("user_a")

        assert await server._embed_batch(["a", "b"]) is None
        assert slim_image == [], f"local ONNX leg was entered: {slim_image}"

    def test_no_chain_and_local_disabled_does_not_spend_the_operator_key(
        self, local_embed_disabled, monkeypatch
    ):
        """Unavailable means None -- never the startup singleton.

        The singleton was resolved from the OPERATOR's process env. Handing it
        to an arbitrary sub bills the operator's provider account for that
        sub's traffic, which the resolver's docstring rules out on purpose.
        """
        from wet_mcp import embedder
        from wet_mcp.embedder import CloudEmbeddingBackend

        operator_singleton = CloudEmbeddingBackend(
            "jina_ai/jina-embeddings-v5-text-small", api_key="operator_key"
        )
        monkeypatch.setattr(embedder, "_backend", operator_singleton)

        store_for_sub("user_a", {"GITHUB_TOKEN": "ghp_x"})
        set_current_sub("user_a")

        assert embedder.resolve_embed_backend_for_request() is not operator_singleton
        assert embedder.resolve_embed_backend_for_request() is None

    def test_no_chain_with_local_enabled_still_returns_shared_local(self):
        """No regression: the local fallback is untouched when local is on."""
        from wet_mcp import embedder
        from wet_mcp.embedder import Qwen3EmbedBackend

        store_for_sub("user_a", {"GITHUB_TOKEN": "ghp_x"})
        set_current_sub("user_a")

        backend = embedder.resolve_embed_backend_for_request()
        assert isinstance(backend, Qwen3EmbedBackend)
        # It is the process-shared instance, not a fresh one per request.
        assert backend is embedder.resolve_embed_backend_for_request()

    def test_cloud_chain_wins_over_the_flag_and_carries_the_subs_key(
        self, local_embed_disabled
    ):
        """A sub WITH a chain is unaffected: the flag only gates the local leg."""
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
        assert backend.api_key == "jina_a"

    def test_sub_none_still_returns_the_startup_singleton(
        self, local_embed_disabled, monkeypatch
    ):
        """Stdio / single-user is out of scope for the per-sub flag branch."""
        from wet_mcp import embedder
        from wet_mcp.embedder import Qwen3EmbedBackend

        sentinel = Qwen3EmbedBackend()
        monkeypatch.setattr(embedder, "_backend", sentinel)
        set_current_sub(None)

        assert embedder.resolve_embed_backend_for_request() is sentinel


# ---------------------------------------------------------------------------
# Reranking
# ---------------------------------------------------------------------------


class TestRerankResolverHonoursDisableLocalRerank:
    def test_no_chain_and_local_disabled_resolves_to_none(self, local_rerank_disabled):
        from wet_mcp.reranker import resolve_rerank_backend_for_request

        store_for_sub("user_a", {"GITHUB_TOKEN": "ghp_x"})
        set_current_sub("user_a")

        assert resolve_rerank_backend_for_request() is None

    async def test_no_chain_and_local_disabled_never_imports_qwen3_embed(
        self, local_rerank_disabled, slim_image
    ):
        """``_rerank_results`` must return the unranked order, importing nothing.

        ``Qwen3Reranker.rerank`` swallows its own exceptions, so the broken
        local leg shows up here as a silent ``logger.warning`` per search
        rather than a traceback -- the import list is the only assertion that
        can tell "reranking was skipped" from "reranking failed quietly".
        """
        from wet_mcp import server

        store_for_sub("user_a", {"GITHUB_TOKEN": "ghp_x"})
        set_current_sub("user_a")

        results = [{"content": "doc-a"}, {"content": "doc-b"}]
        ranked = await server._rerank_results("q", results, top_n=1)
        assert ranked == [{"content": "doc-a"}]
        assert slim_image == [], f"local ONNX leg was entered: {slim_image}"

    def test_no_chain_and_local_disabled_does_not_spend_the_operator_key(
        self, local_rerank_disabled, monkeypatch
    ):
        from wet_mcp import reranker
        from wet_mcp.reranker import CloudReranker

        operator_singleton = CloudReranker(
            model="cohere/rerank-v3.5", api_key="operator_key"
        )
        monkeypatch.setattr(reranker, "_backend", operator_singleton)

        store_for_sub("user_a", {"GITHUB_TOKEN": "ghp_x"})
        set_current_sub("user_a")

        assert reranker.resolve_rerank_backend_for_request() is None

    def test_no_chain_with_local_enabled_still_returns_shared_local(self):
        from wet_mcp import reranker
        from wet_mcp.reranker import Qwen3Reranker

        store_for_sub("user_a", {"GITHUB_TOKEN": "ghp_x"})
        set_current_sub("user_a")

        backend = reranker.resolve_rerank_backend_for_request()
        assert isinstance(backend, Qwen3Reranker)
        assert backend is reranker.resolve_rerank_backend_for_request()

    def test_cloud_chain_wins_over_the_flag_and_carries_the_subs_key(
        self, local_rerank_disabled
    ):
        from wet_mcp.reranker import (
            CloudReranker,
            resolve_rerank_backend_for_request,
        )

        store_for_sub(
            "user_a",
            {"RERANK_MODELS": "cohere/rerank-v3.5", "COHERE_API_KEY": "co_a"},
        )
        set_current_sub("user_a")

        backend = resolve_rerank_backend_for_request()
        assert isinstance(backend, CloudReranker)
        assert backend.model == "cohere/rerank-v3.5"
        assert backend.api_key == "co_a"

    def test_sub_none_still_returns_the_startup_singleton(
        self, local_rerank_disabled, monkeypatch
    ):
        from wet_mcp import reranker
        from wet_mcp.reranker import Qwen3Reranker

        sentinel = Qwen3Reranker()
        monkeypatch.setattr(reranker, "_backend", sentinel)
        set_current_sub(None)

        assert reranker.resolve_rerank_backend_for_request() is sentinel


# ---------------------------------------------------------------------------
# config(action="status")
# ---------------------------------------------------------------------------


class TestConfigStatusReflectsPerRequestResolution:
    """Reported state must be served state, per ``_active_docs_backend``.

    The status handler read the startup singletons, so a sub whose request
    resolves to "nothing" was told ``CloudEmbeddingBackend available=true`` --
    the operator's backend, described to a user who will never be served by it.
    """

    async def test_embedding_reads_unavailable_when_the_request_has_no_backend(
        self, local_embed_disabled, monkeypatch
    ):
        from wet_mcp import embedder
        from wet_mcp.embedder import CloudEmbeddingBackend
        from wet_mcp.server import _handle_config_status

        monkeypatch.setattr(
            embedder,
            "_backend",
            CloudEmbeddingBackend("jina_ai/jina-embeddings-v5-text-small"),
        )
        store_for_sub("user_a", {"GITHUB_TOKEN": "ghp_x"})
        set_current_sub("user_a")

        status = await _handle_config_status()
        assert status["embedding"]["available"] is False
        assert status["embedding"]["backend"] is None

    async def test_embedding_names_the_subs_own_cloud_backend(self, monkeypatch):
        from wet_mcp import embedder
        from wet_mcp.server import _handle_config_status

        monkeypatch.setattr(embedder, "_backend", None)
        store_for_sub(
            "user_a",
            {
                "EMBEDDING_MODELS": "jina_ai/jina-embeddings-v5-text-small",
                "JINA_AI_API_KEY": "jina_a",
            },
        )
        set_current_sub("user_a")

        status = await _handle_config_status()
        assert status["embedding"]["backend"] == "CloudEmbeddingBackend"
        assert status["embedding"]["available"] is True

    async def test_reranker_reads_unavailable_when_the_request_has_no_backend(
        self, local_rerank_disabled, monkeypatch
    ):
        from wet_mcp import reranker
        from wet_mcp.reranker import CloudReranker
        from wet_mcp.server import _handle_config_status

        monkeypatch.setattr(reranker, "_backend", CloudReranker())
        store_for_sub("user_a", {"GITHUB_TOKEN": "ghp_x"})
        set_current_sub("user_a")

        status = await _handle_config_status()
        assert status["reranker"]["available"] is False
        assert status["reranker"]["backend"] is None

    async def test_single_user_still_reports_the_startup_singletons(self, monkeypatch):
        """Existing readers keep the answer they had on stdio / single-user."""
        from wet_mcp import embedder, reranker
        from wet_mcp.embedder import CloudEmbeddingBackend
        from wet_mcp.reranker import CloudReranker
        from wet_mcp.server import _handle_config_status

        monkeypatch.setattr(
            embedder,
            "_backend",
            CloudEmbeddingBackend("jina_ai/jina-embeddings-v5-text-small"),
        )
        monkeypatch.setattr(reranker, "_backend", CloudReranker())
        set_current_sub(None)

        status = await _handle_config_status()
        assert status["embedding"]["backend"] == "CloudEmbeddingBackend"
        assert status["embedding"]["available"] is True
        assert status["reranker"]["backend"] == "CloudReranker"
        assert status["reranker"]["available"] is True

    async def test_status_says_why_embedding_is_unavailable(self, local_embed_disabled):
        """ "available: false" alone reads as a bug report, not a config answer."""
        from wet_mcp.server import _handle_config_status

        store_for_sub("user_a", {"GITHUB_TOKEN": "ghp_x"})
        set_current_sub("user_a")

        reason = (await _handle_config_status())["embedding"]["unavailable_reason"]
        assert reason and "DISABLE_LOCAL_EMBED" in reason


# ---------------------------------------------------------------------------
# Search-time signal
# ---------------------------------------------------------------------------


class TestSearchSignalsKeywordOnlyRetrieval:
    """A keyword-only result set must say so.

    Without a vector the hybrid search silently drops to BM25. The reply is
    shaped identically either way, so the caller reads a thin result set as
    "semantic search found little" when semantic search never ran at all.
    """

    @staticmethod
    def _stub_docs_db(monkeypatch, captured: dict):
        from unittest.mock import MagicMock

        from wet_mcp import server

        db = MagicMock()
        db.get_library.return_value = {"id": "lib1", "discovery_version": 10**6}
        db.get_best_version.return_value = {"id": "ver1", "chunk_count": 3}

        def _search(**kwargs):
            captured.update(kwargs)
            return [{"content": "c", "score": 0.9}]

        db.search.side_effect = _search
        monkeypatch.setattr(server, "_docs_db", db)
        return db

    async def test_keyword_only_reply_names_the_missing_vector_leg(
        self, local_embed_disabled, slim_image, monkeypatch
    ):
        from wet_mcp import server

        captured: dict = {}
        self._stub_docs_db(monkeypatch, captured)
        store_for_sub("user_a", {"GITHUB_TOKEN": "ghp_x"})
        set_current_sub("user_a")

        payload = await server._search_cached_index("fastapi", "routing", None, 10)

        assert payload is not None
        assert captured["query_embedding"] is None
        assert payload["retrieval"] == "keyword_only"
        assert "DISABLE_LOCAL_EMBED" in payload["retrieval_notice"]
        assert slim_image == [], f"local ONNX leg was entered: {slim_image}"

    async def test_hybrid_reply_says_hybrid_and_carries_no_notice(self, monkeypatch):
        from wet_mcp import embedder, server

        class _FakeBackend:
            async def embed_single(self, text, dimensions=None):
                return [0.5] * 4

        monkeypatch.setattr(embedder, "_backend", _FakeBackend())
        set_current_sub(None)

        captured: dict = {}
        self._stub_docs_db(monkeypatch, captured)

        payload = await server._search_cached_index("fastapi", "routing", None, 10)

        assert payload is not None
        assert captured["query_embedding"] == [0.5] * 4
        assert payload["retrieval"] == "hybrid"
        assert payload["retrieval_notice"] is None
