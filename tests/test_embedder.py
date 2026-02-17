"""Tests for src/wet_mcp/embedder.py — Dual-backend embedding.

Covers LiteLLMBackend (batch embedding, batch splitting, retry logic),
Qwen3EmbedBackend (local ONNX embedding), factory functions, and
legacy backward-compatible module-level functions.
"""

import logging
from unittest.mock import MagicMock, call, patch

import pytest

from wet_mcp.embedder import (
    LiteLLMBackend,
    Qwen3EmbedBackend,
    get_backend,
    init_backend,
)

# -----------------------------------------------------------------------
# LiteLLMBackend: embed_texts
# -----------------------------------------------------------------------


class TestLiteLLMBackend:
    def test_embed_texts_success(self):
        """Batch embedding returns correct vectors."""
        backend = LiteLLMBackend("text-embedding-3-small")

        mock_response = MagicMock()
        mock_response.data = [
            {"index": 0, "embedding": [0.1, 0.2, 0.3]},
            {"index": 1, "embedding": [0.4, 0.5, 0.6]},
        ]

        with patch("litellm.embedding", return_value=mock_response):
            vecs = backend.embed_texts(["hello", "world"])

        assert len(vecs) == 2
        assert vecs[0] == [0.1, 0.2, 0.3]
        assert vecs[1] == [0.4, 0.5, 0.6]

    def test_embed_texts_empty_input(self):
        """Empty input returns empty list without API call."""
        backend = LiteLLMBackend("text-embedding-3-small")
        vecs = backend.embed_texts([])
        assert vecs == []

    def test_embed_texts_preserves_order(self):
        """Results are sorted by index even if API returns out-of-order."""
        backend = LiteLLMBackend("text-embedding-3-small")

        mock_response = MagicMock()
        mock_response.data = [
            {"index": 2, "embedding": [0.7, 0.8]},
            {"index": 0, "embedding": [0.1, 0.2]},
            {"index": 1, "embedding": [0.4, 0.5]},
        ]

        with patch("litellm.embedding", return_value=mock_response):
            vecs = backend.embed_texts(["a", "b", "c"])

        assert vecs[0] == [0.1, 0.2]
        assert vecs[1] == [0.4, 0.5]
        assert vecs[2] == [0.7, 0.8]

    def test_embed_texts_with_dimensions(self):
        """Dimensions parameter is passed to LiteLLM."""
        backend = LiteLLMBackend("text-embedding-3-small")

        mock_response = MagicMock()
        mock_response.data = [{"index": 0, "embedding": [0.1]}]

        with patch("litellm.embedding", return_value=mock_response) as mock_embed:
            backend.embed_texts(["test"], dimensions=256)
            mock_embed.assert_called_once_with(
                model="text-embedding-3-small",
                input=["test"],
                dimensions=256,
            )

    def test_embed_texts_no_dimensions(self):
        """No dimensions parameter when not specified."""
        backend = LiteLLMBackend("text-embedding-3-small")

        mock_response = MagicMock()
        mock_response.data = [{"index": 0, "embedding": [0.1]}]

        with patch("litellm.embedding", return_value=mock_response) as mock_embed:
            backend.embed_texts(["test"])
            call_kwargs = mock_embed.call_args[1]
            assert "dimensions" not in call_kwargs

    def test_embed_texts_api_error(self):
        """Non-retryable API errors are raised to caller."""
        backend = LiteLLMBackend("text-embedding-3-small")

        with patch(
            "litellm.embedding",
            side_effect=Exception("Invalid model"),
        ):
            with pytest.raises(Exception, match="Invalid model"):
                backend.embed_texts(["test"])

    def test_embed_single_success(self):
        """Single text embedding returns one vector."""
        backend = LiteLLMBackend("text-embedding-3-small")

        mock_response = MagicMock()
        mock_response.data = [{"index": 0, "embedding": [0.1, 0.2, 0.3]}]

        with patch("litellm.embedding", return_value=mock_response):
            vec = backend.embed_single("hello")

        assert vec == [0.1, 0.2, 0.3]

    def test_check_available(self):
        """Returns dimension count when model is available."""
        backend = LiteLLMBackend("text-embedding-3-small")

        mock_response = MagicMock()
        mock_response.data = [{"index": 0, "embedding": [0.0] * 768}]

        with patch("litellm.embedding", return_value=mock_response):
            dims = backend.check_available()

        assert dims == 768

    def test_check_unavailable(self):
        """Returns 0 when model is not available."""
        backend = LiteLLMBackend("nonexistent")

        with patch(
            "litellm.embedding",
            side_effect=Exception("Invalid API key"),
        ):
            dims = backend.check_available()

        assert dims == 0


# -----------------------------------------------------------------------
# LiteLLMBackend: Batch splitting
# -----------------------------------------------------------------------


class TestBatchSplitting:
    def test_splits_large_batch(self):
        """Texts exceeding MAX_BATCH_SIZE are split into sub-batches."""
        backend = LiteLLMBackend("test-model")
        n = backend.MAX_BATCH_SIZE + 50  # 150 texts -> 2 batches

        def mock_embed(**kwargs):
            batch_input = kwargs["input"]
            resp = MagicMock()
            resp.data = [
                {"index": j, "embedding": [float(j)]} for j in range(len(batch_input))
            ]
            return resp

        with patch("litellm.embedding", side_effect=mock_embed):
            vecs = backend.embed_texts([f"text_{i}" for i in range(n)])

        assert len(vecs) == n

    def test_batch_call_count(self):
        """Correct number of API calls for split batches."""
        backend = LiteLLMBackend("test-model")
        n = backend.MAX_BATCH_SIZE * 2 + 10  # 210 texts -> 3 batches

        def mock_embed(**kwargs):
            resp = MagicMock()
            resp.data = [
                {"index": j, "embedding": [0.0]} for j in range(len(kwargs["input"]))
            ]
            return resp

        with patch("litellm.embedding", side_effect=mock_embed) as mock:
            backend.embed_texts([f"t{i}" for i in range(n)])

        assert mock.call_count == 3

    def test_no_split_under_limit(self):
        """No splitting when under MAX_BATCH_SIZE."""
        backend = LiteLLMBackend("test-model")
        n = backend.MAX_BATCH_SIZE

        def mock_embed(**kwargs):
            resp = MagicMock()
            resp.data = [
                {"index": j, "embedding": [0.0]} for j in range(len(kwargs["input"]))
            ]
            return resp

        with patch("litellm.embedding", side_effect=mock_embed) as mock:
            backend.embed_texts([f"text_{i}" for i in range(n)])

        assert mock.call_count == 1


# -----------------------------------------------------------------------
# LiteLLMBackend: Retry logic
# -----------------------------------------------------------------------


class TestRetryLogic:
    @patch("wet_mcp.embedder.time.sleep")
    def test_retries_on_rate_limit(self, mock_sleep):
        """Retries on rate limit errors with exponential backoff."""
        backend = LiteLLMBackend("test-model")

        success_response = MagicMock()
        success_response.data = [{"index": 0, "embedding": [0.1]}]

        with patch(
            "litellm.embedding",
            side_effect=[
                Exception("429 rate limit exceeded"),
                success_response,
            ],
        ):
            result = backend.embed_texts(["test"])

        assert result == [[0.1]]
        mock_sleep.assert_called_once_with(1.0)

    @patch("wet_mcp.embedder.time.sleep")
    def test_retries_on_server_error(self, mock_sleep):
        """Retries on 5xx server errors."""
        backend = LiteLLMBackend("test-model")

        success_response = MagicMock()
        success_response.data = [{"index": 0, "embedding": [0.2]}]

        with patch(
            "litellm.embedding",
            side_effect=[
                Exception("503 service temporarily unavailable"),
                success_response,
            ],
        ):
            result = backend.embed_texts(["test"])

        assert result == [[0.2]]

    @patch("wet_mcp.embedder.time.sleep")
    def test_no_retry_on_non_retryable(self, mock_sleep):
        """Non-retryable errors fail immediately without retry."""
        backend = LiteLLMBackend("test-model")

        with patch(
            "litellm.embedding",
            side_effect=Exception("Invalid API key"),
        ):
            with pytest.raises(Exception, match="Invalid API key"):
                backend.embed_texts(["test"])

        mock_sleep.assert_not_called()

    @patch("wet_mcp.embedder.time.sleep")
    def test_exponential_backoff(self, mock_sleep):
        """Retry delays use exponential backoff."""
        backend = LiteLLMBackend("test-model")

        success_response = MagicMock()
        success_response.data = [{"index": 0, "embedding": [0.1]}]

        with patch(
            "litellm.embedding",
            side_effect=[
                Exception("429 rate limit"),
                Exception("429 rate limit"),
                success_response,
            ],
        ):
            backend.embed_texts(["test"])

        assert mock_sleep.call_args_list == [call(1.0), call(2.0)]

    @patch("wet_mcp.embedder.time.sleep")
    def test_max_retries_exhausted(self, mock_sleep):
        """Raises after all retries are exhausted."""
        backend = LiteLLMBackend("test-model")

        with patch(
            "litellm.embedding",
            side_effect=Exception("429 rate limit"),
        ):
            with pytest.raises(Exception, match="429 rate limit"):
                backend.embed_texts(["test"])

        # 3 attempts total, 2 sleeps
        assert mock_sleep.call_count == 2


# -----------------------------------------------------------------------
# Qwen3EmbedBackend
# -----------------------------------------------------------------------


class TestQwen3EmbedBackend:
    def test_embed_texts_success(self):
        """Local ONNX embedding returns correct vectors."""
        import numpy as np

        backend = Qwen3EmbedBackend("test-model")
        mock_model = MagicMock()
        mock_model.embed.return_value = iter(
            [
                np.array([0.1, 0.2, 0.3]),
                np.array([0.4, 0.5, 0.6]),
            ]
        )

        with patch.object(backend, "_get_model", return_value=mock_model):
            vecs = backend.embed_texts(["hello", "world"])

        assert len(vecs) == 2
        assert vecs[0] == pytest.approx([0.1, 0.2, 0.3])
        assert vecs[1] == pytest.approx([0.4, 0.5, 0.6])

    def test_embed_texts_empty(self):
        """Empty input returns empty list."""
        backend = Qwen3EmbedBackend()
        assert backend.embed_texts([]) == []

    def test_embed_texts_with_mrl_truncation(self):
        """Dimensions parameter truncates embeddings (MRL)."""
        import numpy as np

        backend = Qwen3EmbedBackend()
        mock_model = MagicMock()
        mock_model.embed.return_value = iter(
            [
                np.array([0.1, 0.2, 0.3, 0.4, 0.5]),
            ]
        )

        with patch.object(backend, "_get_model", return_value=mock_model):
            vecs = backend.embed_texts(["test"], dimensions=3)

        assert len(vecs[0]) == 3
        assert vecs[0] == pytest.approx([0.1, 0.2, 0.3])

    def test_embed_single(self):
        """embed_single delegates to embed_texts."""
        import numpy as np

        backend = Qwen3EmbedBackend()
        mock_model = MagicMock()
        mock_model.embed.return_value = iter([np.array([0.1, 0.2])])

        with patch.object(backend, "_get_model", return_value=mock_model):
            vec = backend.embed_single("test")

        assert vec == pytest.approx([0.1, 0.2])

    def test_check_available_success(self):
        """Returns dimensions when model loads successfully."""
        import numpy as np

        backend = Qwen3EmbedBackend()
        mock_model = MagicMock()
        mock_model.embed.return_value = iter([np.array([0.0] * 1024)])

        with patch.object(backend, "_get_model", return_value=mock_model):
            dims = backend.check_available()

        assert dims == 1024

    def test_check_available_failure(self):
        """Returns 0 when model fails to load."""
        backend = Qwen3EmbedBackend()

        with patch.object(
            backend, "_get_model", side_effect=Exception("ONNX load error")
        ):
            dims = backend.check_available()

        assert dims == 0


# -----------------------------------------------------------------------
# Factory functions
# -----------------------------------------------------------------------


class TestBackendFactory:
    def test_init_litellm_backend(self):
        """init_backend('litellm') creates LiteLLMBackend."""
        backend = init_backend("litellm", "test-model")
        assert isinstance(backend, LiteLLMBackend)
        assert get_backend() is backend

    def test_init_local_backend(self):
        """init_backend('local') creates Qwen3EmbedBackend."""
        backend = init_backend("local")
        assert isinstance(backend, Qwen3EmbedBackend)
        assert get_backend() is backend

    def test_init_litellm_requires_model(self):
        """LiteLLM backend requires model name."""
        with pytest.raises(ValueError, match="model is required"):
            init_backend("litellm")

    def test_init_unknown_backend(self):
        """Unknown backend type raises ValueError."""
        with pytest.raises(ValueError, match="Unknown backend"):
            init_backend("unknown")


# -----------------------------------------------------------------------
# Legacy compatibility functions
# -----------------------------------------------------------------------


class TestLegacyCompat:
    def test_embed_texts_legacy(self):
        """Legacy embed_texts function works."""
        from wet_mcp.embedder import embed_texts

        mock_response = MagicMock()
        mock_response.data = [
            {"index": 0, "embedding": [0.1, 0.2, 0.3]},
        ]

        with patch("litellm.embedding", return_value=mock_response):
            vecs = embed_texts(["hello"], model="text-embedding-3-small")

        assert vecs == [[0.1, 0.2, 0.3]]

    def test_embed_single_legacy(self):
        """Legacy embed_single function works."""
        from wet_mcp.embedder import embed_single

        mock_response = MagicMock()
        mock_response.data = [{"index": 0, "embedding": [0.1, 0.2]}]

        with patch("litellm.embedding", return_value=mock_response):
            vec = embed_single("hello", model="test-model")

        assert vec == [0.1, 0.2]

    def test_check_embedding_available_legacy(self):
        """Legacy check_embedding_available works."""
        from wet_mcp.embedder import check_embedding_available

        mock_response = MagicMock()
        mock_response.data = [{"index": 0, "embedding": [0.0] * 768}]

        with patch("litellm.embedding", return_value=mock_response):
            dims = check_embedding_available("text-embedding-3-small")

        assert dims == 768


# -----------------------------------------------------------------------
# LiteLLM logging suppression
# -----------------------------------------------------------------------


class TestLoggingSuppression:
    def test_litellm_logger_suppressed(self):
        """LiteLLM logger should be suppressed to ERROR level after backend init."""
        _ = LiteLLMBackend("test-model")
        litellm_logger = logging.getLogger("LiteLLM")
        assert litellm_logger.level >= logging.ERROR
