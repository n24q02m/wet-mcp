"""Tests for src/wet_mcp/reranker.py — Dual-backend reranking.

Covers LiteLLMReranker, Qwen3Reranker, factory functions, and
graceful fallback behavior.
"""

from unittest.mock import MagicMock, patch

import pytest

from wet_mcp.reranker import (
    LiteLLMReranker,
    Qwen3Reranker,
    get_reranker,
    init_reranker,
)

# -----------------------------------------------------------------------
# LiteLLMReranker
# -----------------------------------------------------------------------


class TestLiteLLMReranker:
    def test_rerank_success(self):
        """Reranking returns sorted (index, score) tuples."""
        reranker = LiteLLMReranker("cohere/rerank-v3.5")

        mock_response = MagicMock()
        item0 = MagicMock()
        item0.index = 0
        item0.relevance_score = 0.3
        item1 = MagicMock()
        item1.index = 1
        item1.relevance_score = 0.9
        item2 = MagicMock()
        item2.index = 2
        item2.relevance_score = 0.6
        mock_response.results = [item0, item1, item2]

        with patch("litellm.rerank", return_value=mock_response):
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
        reranker = LiteLLMReranker("cohere/rerank-v3.5")
        results = reranker.rerank("query", [], top_n=5)
        assert results == []

    def test_rerank_api_error_returns_empty(self):
        """API errors return empty results (graceful fallback)."""
        reranker = LiteLLMReranker("cohere/rerank-v3.5")

        with patch("litellm.rerank", side_effect=Exception("API error")):
            results = reranker.rerank("query", ["doc1", "doc2"])

        assert results == []

    def test_check_available_success(self):
        """Returns True when model is available."""
        reranker = LiteLLMReranker("cohere/rerank-v3.5")

        mock_response = MagicMock()
        item = MagicMock()
        item.index = 0
        item.relevance_score = 0.5
        mock_response.results = [item]

        with patch("litellm.rerank", return_value=mock_response):
            assert reranker.check_available() is True

    def test_check_available_failure(self):
        """Returns False when model is not available."""
        reranker = LiteLLMReranker("nonexistent")

        with patch("litellm.rerank", side_effect=Exception("Not found")):
            assert reranker.check_available() is False


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
        call_args = mock_model.rerank.call_args[0][0]
        assert call_args == [("my query", "doc1"), ("my query", "doc2")]

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


class TestRerankerFactory:
    def test_init_litellm_reranker(self):
        """init_reranker('litellm') creates LiteLLMReranker."""
        reranker = init_reranker("litellm", "cohere/rerank-v3.5")
        assert isinstance(reranker, LiteLLMReranker)
        assert get_reranker() is reranker

    def test_init_local_reranker(self):
        """init_reranker('local') creates Qwen3Reranker."""
        reranker = init_reranker("local")
        assert isinstance(reranker, Qwen3Reranker)
        assert get_reranker() is reranker

    def test_init_litellm_requires_model(self):
        """LiteLLM reranker requires model name."""
        with pytest.raises(ValueError, match="model is required"):
            init_reranker("litellm")

    def test_init_unknown_backend(self):
        """Unknown backend type raises ValueError."""
        with pytest.raises(ValueError, match="Unknown reranker"):
            init_reranker("unknown")

    def test_get_reranker_none_before_init(self):
        """get_reranker returns None before initialization."""
        import wet_mcp.reranker as mod

        mod._backend = None
        assert get_reranker() is None
