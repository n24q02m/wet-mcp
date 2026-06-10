"""Tests for src/wet_mcp/reranker.py — Dual-backend reranking.

Covers CloudReranker (litellm passthrough via mcp_core.llm), Qwen3Reranker,
factory functions, and graceful fallback behavior.
"""

from unittest.mock import MagicMock, patch

import pytest

from wet_mcp.reranker import (
    CloudReranker,
    Qwen3Reranker,
    get_reranker,
    init_reranker,
)


def _rerank_response(items: list[tuple[int, float]]) -> MagicMock:
    """Build a litellm-shaped RerankResponse mock (.results list of dicts)."""
    mock_response = MagicMock()
    mock_response.results = [
        {"index": idx, "relevance_score": score} for idx, score in items
    ]
    return mock_response


# -----------------------------------------------------------------------
# CloudReranker
# -----------------------------------------------------------------------


class TestCloudReranker:
    def test_rerank_success(self):
        """Reranking returns sorted (index, score) tuples."""
        reranker = CloudReranker(model="rerank-v4.0-pro", api_key="test-key")

        with patch("mcp_core.llm.rerank") as mock_rerank:
            mock_rerank.return_value = _rerank_response([(0, 0.3), (1, 0.9), (2, 0.6)])
            results = reranker.rerank(
                "test query",
                ["doc a", "doc b", "doc c"],
                top_n=2,
            )

        assert len(results) == 2
        # Sorted by score descending
        assert results[0][0] == 1  # index of "doc b"
        assert results[0][1] == 0.9
        assert results[1][0] == 2  # index of "doc c"
        assert results[1][1] == 0.6

    def test_rerank_empty_documents(self):
        """Empty documents return empty results."""
        reranker = CloudReranker(api_key="test-key")
        results = reranker.rerank("query", [], top_n=5)
        assert results == []

    def test_rerank_api_error_returns_empty(self):
        """API errors return empty results (graceful fallback)."""
        reranker = CloudReranker(api_key="test-key")

        with patch("mcp_core.llm.rerank", side_effect=Exception("API error")):
            results = reranker.rerank("query", ["doc1", "doc2"])

        assert results == []

    def test_rerank_forwards_params(self):
        """Model mapping, query, documents, top_n and api_key are forwarded."""
        reranker = CloudReranker(model="rerank-v4.0-pro", api_key="test-key")

        with patch("mcp_core.llm.rerank") as mock_rerank:
            mock_rerank.return_value = _rerank_response([(0, 0.9)])
            reranker.rerank("test query", ["doc a"], top_n=3)

            call_kwargs = mock_rerank.call_args[1]
            assert call_kwargs["model"] == "cohere/rerank-v4.0-pro"
            assert call_kwargs["query"] == "test query"
            assert call_kwargs["documents"] == ["doc a"]
            assert call_kwargs["top_n"] == 3
            assert call_kwargs["api_key"] == "test-key"
            assert call_kwargs["api_base"] is None

    def test_rerank_api_base_env(self, monkeypatch):
        """RERANK_API_BASE env var is forwarded as api_base."""
        monkeypatch.setenv("RERANK_API_BASE", "https://proxy.example.com")
        reranker = CloudReranker(api_key="test-key")

        with patch("mcp_core.llm.rerank") as mock_rerank:
            mock_rerank.return_value = _rerank_response([(0, 0.9)])
            reranker.rerank("query", ["doc"])
            assert mock_rerank.call_args[1]["api_base"] == "https://proxy.example.com"

    def test_check_available_success(self):
        """Returns True when model is available."""
        reranker = CloudReranker(api_key="test-key")

        with patch("mcp_core.llm.rerank") as mock_rerank:
            mock_rerank.return_value = _rerank_response([(0, 0.5)])
            assert reranker.check_available() is True

    def test_check_available_failure(self):
        """Returns False when model is not available."""
        reranker = CloudReranker(api_key="test-key")

        with patch("mcp_core.llm.rerank", side_effect=Exception("Not found")):
            assert reranker.check_available() is False

    def test_default_model(self):
        """Default model is rerank-v4.0-pro (mapped to cohere/ at call time)."""
        reranker = CloudReranker(api_key="test-key")
        assert reranker.model == "rerank-v4.0-pro"
        assert reranker._litellm_model() == "cohere/rerank-v4.0-pro"

    def test_no_api_key_stays_none(self):
        """Without an explicit key, api_key=None lets litellm use env vars."""
        reranker = CloudReranker()
        assert reranker.api_key is None

        with patch("mcp_core.llm.rerank") as mock_rerank:
            mock_rerank.return_value = _rerank_response([(0, 0.5)])
            reranker.rerank("query", ["doc"])
            assert mock_rerank.call_args[1]["api_key"] is None


class TestCloudRerankerModelMapping:
    """_litellm_model maps wet's model naming to litellm provider prefixes."""

    def test_prefixed_models_pass_through(self):
        assert (
            CloudReranker(model="cohere/rerank-v4.0-pro")._litellm_model()
            == "cohere/rerank-v4.0-pro"
        )
        assert (
            CloudReranker(model="jina_ai/jina-reranker-v3")._litellm_model()
            == "jina_ai/jina-reranker-v3"
        )

    def test_bare_jina_gets_prefix(self):
        assert (
            CloudReranker(model="jina-reranker-v3")._litellm_model()
            == "jina_ai/jina-reranker-v3"
        )

    def test_bare_cohere_gets_prefix(self):
        assert (
            CloudReranker(model="rerank-v3.5")._litellm_model() == "cohere/rerank-v3.5"
        )


# -----------------------------------------------------------------------
# Qwen3Reranker
# -----------------------------------------------------------------------


class TestQwen3Reranker:
    def test_rerank_success(self):
        """Local cross-encoder reranking returns sorted results."""
        reranker = Qwen3Reranker("test-model")

        mock_model = MagicMock()
        # Simulate P(yes) scores for 3 documents
        mock_model.rerank.return_value = iter([0.3, 0.9, 0.6])

        with patch.object(reranker, "_get_model", return_value=mock_model):
            results = reranker.rerank(
                "test query",
                ["doc a", "doc b", "doc c"],
                top_n=2,
            )

        assert len(results) == 2
        # Sorted by score descending
        assert results[0][0] == 1  # doc b
        assert results[0][1] == 0.9
        assert results[1][0] == 2  # doc c
        assert results[1][1] == 0.6

    def test_rerank_empty_documents(self):
        """Empty documents return empty results."""
        reranker = Qwen3Reranker()
        results = reranker.rerank("query", [])
        assert results == []

    def test_rerank_passes_pairs(self):
        """Reranker receives (query, document) pairs."""
        reranker = Qwen3Reranker()

        mock_model = MagicMock()
        mock_model.rerank.return_value = iter([0.5, 0.8])

        with patch.object(reranker, "_get_model", return_value=mock_model):
            reranker.rerank("my query", ["doc1", "doc2"])

        # Verify pairs passed to model
        assert mock_model.rerank.call_args[0][0] == "my query"
        assert mock_model.rerank.call_args[0][1] == ["doc1", "doc2"]

    def test_rerank_error_returns_empty(self):
        """Model errors return empty results (graceful fallback)."""
        reranker = Qwen3Reranker()

        with patch.object(reranker, "_get_model", side_effect=Exception("ONNX error")):
            results = reranker.rerank("query", ["doc1"])

        assert results == []

    def test_check_available_success(self):
        """Returns True when model loads successfully."""
        reranker = Qwen3Reranker()

        mock_model = MagicMock()
        mock_model.rerank.return_value = iter([0.5])

        with patch.object(reranker, "_get_model", return_value=mock_model):
            assert reranker.check_available() is True

    def test_check_available_failure(self):
        """Returns False when model fails to load."""
        reranker = Qwen3Reranker()

        with patch.object(reranker, "_get_model", side_effect=Exception("Load error")):
            assert reranker.check_available() is False


# -----------------------------------------------------------------------
# Factory functions
# -----------------------------------------------------------------------


class TestCloudRerankerApiKeyValidation:
    """check_available() distinguishes API key errors from other failures."""

    def test_api_key_401_returns_false(self):
        """401 errors return False."""
        reranker = CloudReranker(api_key="bad-key")
        with patch("mcp_core.llm.rerank", side_effect=Exception("401 Unauthorized")):
            assert reranker.check_available() is False

    def test_api_key_403_returns_false(self):
        """403 errors return False."""
        reranker = CloudReranker(api_key="bad-key")
        with patch("mcp_core.llm.rerank", side_effect=Exception("403 Forbidden")):
            assert reranker.check_available() is False

    def test_invalid_key_detected(self):
        """'invalid' keyword triggers warning path."""
        reranker = CloudReranker(api_key="bad-key")
        with patch("mcp_core.llm.rerank", side_effect=Exception("Invalid API key")):
            assert reranker.check_available() is False

    def test_non_auth_error_returns_false(self):
        """Non-auth errors also return False."""
        reranker = CloudReranker(api_key="test-key")
        with patch("mcp_core.llm.rerank", side_effect=Exception("Model not found")):
            assert reranker.check_available() is False

    def test_success_returns_true(self):
        """Successful check returns True."""
        reranker = CloudReranker(api_key="test-key")
        with patch("mcp_core.llm.rerank") as mock_rerank:
            mock_rerank.return_value = _rerank_response([(0, 0.9)])
            assert reranker.check_available() is True


class TestQwen3RerankerGetModelWarning:
    """_get_model() and check_available edge cases."""

    def test_check_available_import_error(self):
        """Returns False when qwen3-embed is not installed."""
        reranker = Qwen3Reranker()
        with patch.object(reranker, "_get_model", side_effect=ImportError("No module")):
            assert reranker.check_available() is False

    def test_check_available_success(self):
        """Returns True when local reranker works."""
        reranker = Qwen3Reranker()
        mock_model = MagicMock()
        mock_model.rerank.return_value = iter([0.8])
        with patch.object(reranker, "_get_model", return_value=mock_model):
            assert reranker.check_available() is True


class TestRerankerFactory:
    def test_init_cloud_reranker(self):
        """init_reranker('cloud') creates CloudReranker."""
        reranker = init_reranker("cloud", api_key="test-key")
        assert isinstance(reranker, CloudReranker)
        assert get_reranker() is reranker

    def test_init_local_reranker(self):
        """init_reranker('local') creates Qwen3Reranker."""
        reranker = init_reranker("local")
        assert isinstance(reranker, Qwen3Reranker)
        assert get_reranker() is reranker

    def test_init_unknown_backend(self):
        """Unknown backend type raises ValueError."""
        with pytest.raises(ValueError, match="Unknown reranker"):
            init_reranker("unknown")

    def test_get_reranker_none_before_init(self):
        """get_reranker returns None before initialization."""
        import wet_mcp.reranker as mod

        mod._backend = None
        assert get_reranker() is None

    def test_init_cloud_default_model(self):
        """Cloud reranker uses default model when none specified."""
        reranker = init_reranker("cloud", api_key="test-key")
        assert isinstance(reranker, CloudReranker)
        assert reranker.model == "rerank-v4.0-pro"

    def test_init_cloud_custom_model(self):
        """Cloud reranker accepts custom model."""
        reranker = init_reranker("cloud", model="rerank-v3.5", api_key="test-key")
        assert isinstance(reranker, CloudReranker)
        assert reranker.model == "rerank-v3.5"
