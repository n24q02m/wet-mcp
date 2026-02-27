"""Tests for embedding functionality (local and cloud)."""

import time
from unittest.mock import MagicMock, call, patch

import pytest

from wet_mcp.embedder import (
    LiteLLMBackend,
    Qwen3EmbedBackend,
    get_backend,
    init_backend,
)


@pytest.fixture
def mock_litellm():
    with patch("litellm.embedding") as mock_embedding:
        # Mock response structure for a single item
        mock_response = MagicMock()
        mock_response.data = [{"index": 0, "embedding": [0.1, 0.2, 0.3]}]
        mock_embedding.return_value = mock_response
        yield mock_embedding


@pytest.fixture
def mock_qwen3():
    with patch("qwen3_embed.TextEmbedding") as mock_cls:
        mock_instance = MagicMock()
        # Mock numpy array tolist() behavior
        mock_array = MagicMock()
        mock_array.tolist.return_value = [0.1, 0.2, 0.3]
        # Make the mock array have a length for len() calls
        mock_array.__len__ = MagicMock(return_value=3)
        mock_instance.embed.return_value = [mock_array]
        mock_instance.query_embed.return_value = [mock_array]
        mock_cls.return_value = mock_instance
        yield mock_cls


def test_init_backend_litellm():
    backend = init_backend("litellm", "test-model")
    assert isinstance(backend, LiteLLMBackend)
    assert backend.model == "test-model"
    assert get_backend() is backend


def test_init_backend_local():
    backend = init_backend("local", "test-local-model")
    assert isinstance(backend, Qwen3EmbedBackend)
    assert backend._model_name == "test-local-model"
    assert get_backend() is backend


def test_litellm_embed_single(mock_litellm):
    backend = LiteLLMBackend("test-model")
    embedding = backend.embed_single("test text")

    assert embedding == [0.1, 0.2, 0.3]
    mock_litellm.assert_called_once()
    args, kwargs = mock_litellm.call_args
    assert kwargs["model"] == "test-model"
    assert kwargs["input"] == ["test text"]


def test_litellm_embed_batch_small(mock_litellm):
    """Test embedding a small batch (no splitting)."""
    backend = LiteLLMBackend("test-model")

    # Setup mock to return two embeddings
    mock_response = MagicMock()
    mock_response.data = [
        {"index": 0, "embedding": [0.1]},
        {"index": 1, "embedding": [0.2]}
    ]
    mock_litellm.return_value = mock_response

    embeddings = backend.embed_texts(["text1", "text2"])

    assert len(embeddings) == 2
    assert embeddings[0] == [0.1]
    assert embeddings[1] == [0.2]
    mock_litellm.assert_called_once()
    args, kwargs = mock_litellm.call_args
    assert kwargs["input"] == ["text1", "text2"]


def test_litellm_embed_batch_splitting(mock_litellm):
    """Test that large batches are split correctly."""
    backend = LiteLLMBackend("test-model")
    # Force small batch size for testing
    backend.MAX_BATCH_SIZE = 2

    # 3 inputs -> should split into [2, 1]
    inputs = ["t1", "t2", "t3"]

    # Mock responses for each call
    resp1 = MagicMock()
    resp1.data = [{"index": 0, "embedding": [0.1]}, {"index": 1, "embedding": [0.2]}]

    resp2 = MagicMock()
    resp2.data = [{"index": 0, "embedding": [0.3]}]

    mock_litellm.side_effect = [resp1, resp2]

    embeddings = backend.embed_texts(inputs)

    assert len(embeddings) == 3
    assert embeddings == [[0.1], [0.2], [0.3]]

    assert mock_litellm.call_count == 2
    # Check calls
    call1 = call(model="test-model", input=["t1", "t2"])
    call2 = call(model="test-model", input=["t3"])
    mock_litellm.assert_has_calls([call1, call2])


def test_litellm_retry_logic(mock_litellm):
    """Test retry logic on transient errors."""
    backend = LiteLLMBackend("test-model")

    # Fail twice with RateLimitError, then succeed
    error = Exception("Rate limit exceeded (429)")
    success_resp = MagicMock()
    success_resp.data = [{"index": 0, "embedding": [0.1]}]

    mock_litellm.side_effect = [error, error, success_resp]

    # Mock time.sleep to avoid waiting
    with patch("time.sleep") as mock_sleep:
        embeddings = backend.embed_texts(["test"])

        assert embeddings == [[0.1]]
        assert mock_litellm.call_count == 3
        assert mock_sleep.call_count == 2


def test_litellm_retry_failure(mock_litellm):
    """Test that retries eventually fail."""
    backend = LiteLLMBackend("test-model")

    # Always fail
    error = Exception("Rate limit exceeded (429)")
    mock_litellm.side_effect = error

    with patch("time.sleep"):
        with pytest.raises(Exception) as exc:
            backend.embed_texts(["test"])

        assert "Rate limit" in str(exc.value)
        # Should try MAX_RETRIES (3) times
        assert mock_litellm.call_count == 3


def test_litellm_no_retry_on_fatal_error(mock_litellm):
    """Test that fatal errors (e.g. 400 Bad Request) are not retried."""
    backend = LiteLLMBackend("test-model")

    # Fail with non-retriable error
    error = Exception("Invalid request (400)")
    mock_litellm.side_effect = error

    with patch("time.sleep") as mock_sleep:
        with pytest.raises(Exception):
            backend.embed_texts(["test"])

        # Should fail immediately
        assert mock_litellm.call_count == 1
        mock_sleep.assert_not_called()


def test_litellm_check_available(mock_litellm):
    backend = LiteLLMBackend("test-model")
    dims = backend.check_available()
    assert dims == 3
    mock_litellm.assert_called_with(model="test-model", input=["test"])


def test_qwen3_embed_single(mock_qwen3):
    backend = Qwen3EmbedBackend()
    embedding = backend.embed_single("test text")

    assert embedding == [0.1, 0.2, 0.3]
    mock_qwen3.return_value.embed.assert_called_with(["test text"])


def test_qwen3_embed_query(mock_qwen3):
    backend = Qwen3EmbedBackend()
    embedding = backend.embed_single_query("test query")

    assert embedding == [0.1, 0.2, 0.3]
    mock_qwen3.return_value.query_embed.assert_called_with("test query")


def test_qwen3_check_available(mock_qwen3):
    backend = Qwen3EmbedBackend()
    dims = backend.check_available()
    assert dims == 3
    mock_qwen3.return_value.embed.assert_called_with(["test"])
