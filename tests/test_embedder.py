"""Tests for src/wet_mcp/embedder.py — LiteLLM embedding wrapper.

Covers embed_texts, embed_single, check_embedding_available with
mocked LiteLLM responses, error handling, batch splitting, and retry logic.
"""

import logging
from unittest.mock import MagicMock, call, patch

import pytest

# -----------------------------------------------------------------------
# embed_texts
# -----------------------------------------------------------------------


class TestEmbedTexts:
    def test_embed_texts_success(self):
        """Batch embedding returns correct vectors."""
        from wet_mcp.embedder import embed_texts

        mock_response = MagicMock()
        mock_response.data = [
            {"index": 0, "embedding": [0.1, 0.2, 0.3]},
            {"index": 1, "embedding": [0.4, 0.5, 0.6]},
        ]

        with patch("wet_mcp.embedder.litellm_embedding", return_value=mock_response):
            vecs = embed_texts(["hello", "world"], model="text-embedding-3-small")

        assert len(vecs) == 2
        assert vecs[0] == [0.1, 0.2, 0.3]
        assert vecs[1] == [0.4, 0.5, 0.6]

    def test_embed_texts_empty_input(self):
        """Empty input returns empty list without API call."""
        from wet_mcp.embedder import embed_texts

        with patch("wet_mcp.embedder.litellm_embedding") as mock_embed:
            vecs = embed_texts([], model="text-embedding-3-small")
            assert vecs == []
            mock_embed.assert_not_called()

    def test_embed_texts_preserves_order(self):
        """Results are sorted by index even if API returns out-of-order."""
        from wet_mcp.embedder import embed_texts

        mock_response = MagicMock()
        # Out of order
        mock_response.data = [
            {"index": 2, "embedding": [0.7, 0.8]},
            {"index": 0, "embedding": [0.1, 0.2]},
            {"index": 1, "embedding": [0.4, 0.5]},
        ]

        with patch("wet_mcp.embedder.litellm_embedding", return_value=mock_response):
            vecs = embed_texts(["a", "b", "c"], model="text-embedding-3-small")

        assert vecs[0] == [0.1, 0.2]
        assert vecs[1] == [0.4, 0.5]
        assert vecs[2] == [0.7, 0.8]

    def test_embed_texts_with_dimensions(self):
        """Dimensions parameter is passed to LiteLLM."""
        from wet_mcp.embedder import embed_texts

        mock_response = MagicMock()
        mock_response.data = [{"index": 0, "embedding": [0.1]}]

        with patch(
            "wet_mcp.embedder.litellm_embedding", return_value=mock_response
        ) as mock_embed:
            embed_texts(["test"], model="text-embedding-3-small", dimensions=256)
            mock_embed.assert_called_once_with(
                model="text-embedding-3-small",
                input=["test"],
                dimensions=256,
            )

    def test_embed_texts_no_dimensions(self):
        """No dimensions parameter when not specified."""
        from wet_mcp.embedder import embed_texts

        mock_response = MagicMock()
        mock_response.data = [{"index": 0, "embedding": [0.1]}]

        with patch(
            "wet_mcp.embedder.litellm_embedding", return_value=mock_response
        ) as mock_embed:
            embed_texts(["test"], model="text-embedding-3-small")
            call_kwargs = mock_embed.call_args[1]
            assert "dimensions" not in call_kwargs

    def test_embed_texts_api_error(self):
        """Non-retryable API errors are raised to caller."""
        from wet_mcp.embedder import embed_texts

        with patch(
            "wet_mcp.embedder.litellm_embedding",
            side_effect=Exception("Invalid model"),
        ):
            with pytest.raises(Exception, match="Invalid model"):
                embed_texts(["test"], model="text-embedding-3-small")


# -----------------------------------------------------------------------
# Batch splitting
# -----------------------------------------------------------------------


class TestBatchSplitting:
    def test_splits_large_batch(self):
        """Texts exceeding MAX_BATCH_SIZE are split into sub-batches."""
        from wet_mcp.embedder import MAX_BATCH_SIZE, embed_texts

        n = MAX_BATCH_SIZE + 50  # 150 texts -> 2 batches (100 + 50)
        texts = [f"text_{i}" for i in range(n)]

        def mock_embed(**kwargs):
            batch_input = kwargs["input"]
            resp = MagicMock()
            resp.data = [
                {"index": j, "embedding": [float(j)]} for j in range(len(batch_input))
            ]
            return resp

        with patch("wet_mcp.embedder.litellm_embedding", side_effect=mock_embed):
            vecs = embed_texts(texts, model="test-model")

        assert len(vecs) == n

    def test_batch_call_count(self):
        """Correct number of API calls for split batches."""
        from wet_mcp.embedder import MAX_BATCH_SIZE, embed_texts

        n = MAX_BATCH_SIZE * 2 + 10  # 210 texts -> 3 batches

        def mock_embed(**kwargs):
            resp = MagicMock()
            resp.data = [
                {"index": j, "embedding": [0.0]} for j in range(len(kwargs["input"]))
            ]
            return resp

        with patch(
            "wet_mcp.embedder.litellm_embedding", side_effect=mock_embed
        ) as mock:
            embed_texts([f"t{i}" for i in range(n)], model="m")

        assert mock.call_count == 3

    def test_no_split_under_limit(self):
        """No splitting when under MAX_BATCH_SIZE."""
        from wet_mcp.embedder import MAX_BATCH_SIZE, embed_texts

        n = MAX_BATCH_SIZE  # Exactly at limit
        texts = [f"text_{i}" for i in range(n)]

        def mock_embed(**kwargs):
            resp = MagicMock()
            resp.data = [
                {"index": j, "embedding": [0.0]} for j in range(len(kwargs["input"]))
            ]
            return resp

        with patch(
            "wet_mcp.embedder.litellm_embedding", side_effect=mock_embed
        ) as mock:
            embed_texts(texts, model="m")

        assert mock.call_count == 1


# -----------------------------------------------------------------------
# Retry logic
# -----------------------------------------------------------------------


class TestRetryLogic:
    @patch("wet_mcp.embedder.time.sleep")
    def test_retries_on_rate_limit(self, mock_sleep):
        """Retries on rate limit errors with exponential backoff."""
        from wet_mcp.embedder import embed_texts

        success_response = MagicMock()
        success_response.data = [{"index": 0, "embedding": [0.1]}]

        with patch(
            "wet_mcp.embedder.litellm_embedding",
            side_effect=[
                Exception("429 rate limit exceeded"),
                success_response,
            ],
        ):
            result = embed_texts(["test"], model="m")

        assert result == [[0.1]]
        mock_sleep.assert_called_once_with(1.0)

    @patch("wet_mcp.embedder.time.sleep")
    def test_retries_on_server_error(self, mock_sleep):
        """Retries on 5xx server errors."""
        from wet_mcp.embedder import embed_texts

        success_response = MagicMock()
        success_response.data = [{"index": 0, "embedding": [0.2]}]

        with patch(
            "wet_mcp.embedder.litellm_embedding",
            side_effect=[
                Exception("503 service temporarily unavailable"),
                success_response,
            ],
        ):
            result = embed_texts(["test"], model="m")

        assert result == [[0.2]]

    @patch("wet_mcp.embedder.time.sleep")
    def test_no_retry_on_non_retryable(self, mock_sleep):
        """Non-retryable errors fail immediately without retry."""
        from wet_mcp.embedder import embed_texts

        with patch(
            "wet_mcp.embedder.litellm_embedding",
            side_effect=Exception("Invalid API key"),
        ):
            with pytest.raises(Exception, match="Invalid API key"):
                embed_texts(["test"], model="m")

        mock_sleep.assert_not_called()

    @patch("wet_mcp.embedder.time.sleep")
    def test_exponential_backoff(self, mock_sleep):
        """Retry delays use exponential backoff."""
        from wet_mcp.embedder import embed_texts

        success_response = MagicMock()
        success_response.data = [{"index": 0, "embedding": [0.1]}]

        with patch(
            "wet_mcp.embedder.litellm_embedding",
            side_effect=[
                Exception("429 rate limit"),
                Exception("429 rate limit"),
                success_response,
            ],
        ):
            embed_texts(["test"], model="m")

        assert mock_sleep.call_args_list == [call(1.0), call(2.0)]

    @patch("wet_mcp.embedder.time.sleep")
    def test_max_retries_exhausted(self, mock_sleep):
        """Raises after all retries are exhausted."""
        from wet_mcp.embedder import embed_texts

        with patch(
            "wet_mcp.embedder.litellm_embedding",
            side_effect=Exception("429 rate limit"),
        ):
            with pytest.raises(Exception, match="429 rate limit"):
                embed_texts(["test"], model="m")

        # 3 attempts total, 2 sleeps
        assert mock_sleep.call_count == 2


# -----------------------------------------------------------------------
# embed_single
# -----------------------------------------------------------------------


class TestEmbedSingle:
    def test_embed_single_success(self):
        """Single text embedding returns one vector."""
        from wet_mcp.embedder import embed_single

        mock_response = MagicMock()
        mock_response.data = [{"index": 0, "embedding": [0.1, 0.2, 0.3]}]

        with patch("wet_mcp.embedder.litellm_embedding", return_value=mock_response):
            vec = embed_single("hello", model="text-embedding-3-small")

        assert vec == [0.1, 0.2, 0.3]

    def test_embed_single_error(self):
        """embed_single propagates errors."""
        from wet_mcp.embedder import embed_single

        with patch(
            "wet_mcp.embedder.litellm_embedding",
            side_effect=Exception("Model not found"),
        ):
            with pytest.raises(Exception, match="Model not found"):
                embed_single("test", model="nonexistent-model")


# -----------------------------------------------------------------------
# check_embedding_available
# -----------------------------------------------------------------------


class TestCheckEmbeddingAvailable:
    def test_available_model(self):
        """Returns dimension count when model is available."""
        from wet_mcp.embedder import check_embedding_available

        mock_response = MagicMock()
        mock_response.data = [{"index": 0, "embedding": [0.0] * 768}]

        with patch("wet_mcp.embedder.litellm_embedding", return_value=mock_response):
            dims = check_embedding_available("text-embedding-3-small")

        assert dims == 768

    def test_unavailable_model(self):
        """Returns 0 when model is not available."""
        from wet_mcp.embedder import check_embedding_available

        with patch(
            "wet_mcp.embedder.litellm_embedding",
            side_effect=Exception("Invalid API key"),
        ):
            dims = check_embedding_available("nonexistent-model")

        assert dims == 0

    def test_empty_response(self):
        """Returns 0 when API returns empty data."""
        from wet_mcp.embedder import check_embedding_available

        mock_response = MagicMock()
        mock_response.data = []

        with patch("wet_mcp.embedder.litellm_embedding", return_value=mock_response):
            dims = check_embedding_available("text-embedding-3-small")

        assert dims == 0

    def test_sends_test_input(self):
        """check_embedding_available sends 'test' as input."""
        from wet_mcp.embedder import check_embedding_available

        mock_response = MagicMock()
        mock_response.data = [{"index": 0, "embedding": [0.1]}]

        with patch(
            "wet_mcp.embedder.litellm_embedding", return_value=mock_response
        ) as mock_embed:
            check_embedding_available("text-embedding-3-small")
            mock_embed.assert_called_once_with(
                model="text-embedding-3-small", input=["test"]
            )


# -----------------------------------------------------------------------
# LiteLLM logging suppression
# -----------------------------------------------------------------------


class TestLoggingSuppression:
    def test_litellm_logger_suppressed(self):
        """LiteLLM logger should be suppressed to ERROR level."""
        litellm_logger = logging.getLogger("LiteLLM")
        assert litellm_logger.level >= logging.ERROR
