"""Tests for src/wet_mcp/reranker.py — Dual-backend reranking.

Covers CohereReranker, Qwen3Reranker, factory functions, and
graceful fallback behavior.
"""

from unittest.mock import MagicMock, patch

import pytest

from wet_mcp.reranker import (
    CohereReranker,
    Qwen3Reranker,
    get_reranker,
    init_reranker,
)

# -----------------------------------------------------------------------
# CohereReranker
# -----------------------------------------------------------------------


class TestCohereReranker:
    def test_rerank_success(self):
        """Reranking returns sorted (index, score) tuples."""
        reranker = CohereReranker(model="rerank-v4.0-pro", api_key="test-key")

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

        mock_client = MagicMock()
        mock_client.rerank.return_value = mock_response

        with patch.object(reranker, "_get_client", return_value=mock_client):
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
        reranker = CohereReranker(api_key="test-key")
        results = reranker.rerank("query", [], top_n=5)
        assert results == []

    def test_rerank_api_error_returns_empty(self):
        """API errors return empty results (graceful fallback)."""
        reranker = CohereReranker(api_key="test-key")

        mock_client = MagicMock()
        mock_client.rerank.side_effect = Exception("API error")

        with patch.object(reranker, "_get_client", return_value=mock_client):
            results = reranker.rerank("query", ["doc1", "doc2"])

        assert results == []

    def test_check_available_success(self):
        """Returns True when model is available."""
        reranker = CohereReranker(api_key="test-key")

        mock_response = MagicMock()
        item = MagicMock()
        item.index = 0
        item.relevance_score = 0.5
        mock_response.results = [item]

        mock_client = MagicMock()
        mock_client.rerank.return_value = mock_response

        with patch.object(reranker, "_get_client", return_value=mock_client):
            assert reranker.check_available() is True

    def test_check_available_failure(self):
        """Returns False when model is not available."""
        reranker = CohereReranker(api_key="test-key")

        mock_client = MagicMock()
        mock_client.rerank.side_effect = Exception("Not found")

        with patch.object(reranker, "_get_client", return_value=mock_client):
            assert reranker.check_available() is False

    def test_default_model(self):
        """Default model is rerank-v4.0-pro."""
        reranker = CohereReranker(api_key="test-key")
        assert reranker.model == "rerank-v4.0-pro"

    def test_api_key_from_env(self):
        """API key falls back to COHERE_API_KEY env var."""
        with patch.dict("os.environ", {"COHERE_API_KEY": "env-key"}, clear=False):
            reranker = CohereReranker()
            assert reranker.api_key == "env-key"

    def test_api_key_from_co_env(self):
        """API key falls back to CO_API_KEY env var."""
        with patch.dict(
            "os.environ",
            {"CO_API_KEY": "co-key"},
            clear=False,
        ):
            # Remove COHERE_API_KEY if present
            import os

            env = os.environ.copy()
            env.pop("COHERE_API_KEY", None)
            env["CO_API_KEY"] = "co-key"
            with patch.dict("os.environ", env, clear=True):
                reranker = CohereReranker()
                assert reranker.api_key == "co-key"


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


class TestCohereRerankerApiKeyValidation:
    """check_available() distinguishes API key errors from other failures."""

    def test_api_key_401_returns_false(self):
        """401 errors return False."""
        reranker = CohereReranker(api_key="bad-key")
        mock_client = MagicMock()
        mock_client.rerank.side_effect = Exception("401 Unauthorized")
        with patch.object(reranker, "_get_client", return_value=mock_client):
            assert reranker.check_available() is False

    def test_api_key_403_returns_false(self):
        """403 errors return False."""
        reranker = CohereReranker(api_key="bad-key")
        mock_client = MagicMock()
        mock_client.rerank.side_effect = Exception("403 Forbidden")
        with patch.object(reranker, "_get_client", return_value=mock_client):
            assert reranker.check_available() is False

    def test_invalid_key_detected(self):
        """'invalid' keyword triggers warning path."""
        reranker = CohereReranker(api_key="bad-key")
        mock_client = MagicMock()
        mock_client.rerank.side_effect = Exception("Invalid API key")
        with patch.object(reranker, "_get_client", return_value=mock_client):
            assert reranker.check_available() is False

    def test_non_auth_error_returns_false(self):
        """Non-auth errors also return False."""
        reranker = CohereReranker(api_key="test-key")
        mock_client = MagicMock()
        mock_client.rerank.side_effect = Exception("Model not found")
        with patch.object(reranker, "_get_client", return_value=mock_client):
            assert reranker.check_available() is False

    def test_success_returns_true(self):
        """Successful check returns True."""
        reranker = CohereReranker(api_key="test-key")
        mock_response = MagicMock()
        mock_response.results = [MagicMock(index=0, relevance_score=0.9)]
        mock_client = MagicMock()
        mock_client.rerank.return_value = mock_response
        with patch.object(reranker, "_get_client", return_value=mock_client):
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
        """init_reranker('cloud') creates CohereReranker."""
        reranker = init_reranker("cloud", api_key="test-key")
        assert isinstance(reranker, CohereReranker)
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
        assert isinstance(reranker, CohereReranker)
        assert reranker.model == "rerank-v4.0-pro"

    def test_init_cloud_custom_model(self):
        """Cloud reranker accepts custom model."""
        reranker = init_reranker("cloud", model="rerank-v3.5", api_key="test-key")
        assert isinstance(reranker, CohereReranker)
        assert reranker.model == "rerank-v3.5"
