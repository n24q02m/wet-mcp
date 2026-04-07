"""Tests for src/wet_mcp/embedder.py -- Dual-backend embedding.

Covers CloudEmbeddingBackend (native SDK providers: OpenAI, Cohere, Gemini, Jina),
batch splitting, retry logic, Qwen3EmbedBackend (local ONNX), factory functions,
and provider detection helpers.
"""

from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

from wet_mcp.embedder import (
    CloudEmbeddingBackend,
    Qwen3EmbedBackend,
    _detect_embedding_provider,
    _is_retryable,
    _is_unsupported_param,
    _strip_provider,
    get_backend,
    init_backend,
)

# -----------------------------------------------------------------------
# Helper function tests
# -----------------------------------------------------------------------


class TestHelpers:
    async def test_detect_provider_gemini(self):
        assert _detect_embedding_provider("gemini/gemini-embedding-001") == "gemini"
        assert _detect_embedding_provider("gemini-embedding-001") == "gemini"

    async def test_detect_provider_openai(self):
        assert _detect_embedding_provider("text-embedding-3-small") == "openai"
        assert _detect_embedding_provider("openai/text-embedding-3-small") == "openai"

    async def test_detect_provider_cohere(self):
        assert _detect_embedding_provider("embed-multilingual-v3.0") == "cohere"
        assert _detect_embedding_provider("cohere/embed-v4") == "cohere"

    async def test_detect_provider_jina(self):
        assert _detect_embedding_provider("jina_ai/jina-embeddings-v3") == "jina"
        assert _detect_embedding_provider("jina-embeddings-v3") == "jina"

    async def test_detect_provider_fallback_env(self):
        with patch.dict("os.environ", {"GEMINI_API_KEY": "k"}, clear=False):
            assert _detect_embedding_provider("unknown-model") == "gemini"

    async def test_detect_provider_fallback_default(self):
        with patch.dict(
            "os.environ",
            {},
            clear=True,
        ):
            # Remove all provider env vars
            import os

            for k in (
                "GEMINI_API_KEY",
                "GOOGLE_API_KEY",
                "OPENAI_API_KEY",
                "COHERE_API_KEY",
            ):
                os.environ.pop(k, None)
            assert _detect_embedding_provider("unknown-model") == "openai"

    async def test_strip_provider(self):
        assert _strip_provider("gemini/model-name") == "model-name"
        assert _strip_provider("model-name") == "model-name"

    async def test_is_retryable(self):
        assert _is_retryable(Exception("429 rate limit exceeded"))
        assert _is_retryable(Exception("503 service temporarily unavailable"))
        assert _is_retryable(Exception("connection timeout"))
        assert not _is_retryable(Exception("Invalid API key"))

    async def test_is_unsupported_param(self):
        assert _is_unsupported_param(
            Exception("does not support parameters: dimensions"), "dimensions"
        )
        assert _is_unsupported_param(
            Exception("output_dimension is not supported for this model"), "dimensions"
        )
        assert not _is_unsupported_param(Exception("rate limit"), "dimensions")


# -----------------------------------------------------------------------
# CloudEmbeddingBackend: embed_texts (mocking _call_provider)
# -----------------------------------------------------------------------


class TestCloudEmbeddingBackend:
    async def test_embed_texts_success(self):
        """Batch embedding returns correct vectors."""
        backend = CloudEmbeddingBackend("text-embedding-3-small")

        with patch.object(backend, "_call_provider", new_callable=AsyncMock,
            return_value=[[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]],
        ):
            vecs = await backend.embed_texts(["hello", "world"])

        assert len(vecs) == 2
        assert vecs[0] == [0.1, 0.2, 0.3]
        assert vecs[1] == [0.4, 0.5, 0.6]

    async def test_embed_texts_empty_input(self):
        """Empty input returns empty list without API call."""
        backend = CloudEmbeddingBackend("text-embedding-3-small")
        vecs = await backend.embed_texts([])
        assert vecs == []

    async def test_embed_texts_with_dimensions(self):
        """Dimensions parameter is passed through to _call_provider."""
        backend = CloudEmbeddingBackend("text-embedding-3-small")

        with patch.object(backend, "_call_provider", new_callable=AsyncMock, return_value=[[0.1]]) as mock_call:
            await backend.embed_texts(["test"], dimensions=256)
            mock_call.assert_called_once_with(["test"], 256)

    async def test_embed_texts_no_dimensions(self):
        """No dimensions parameter when not specified."""
        backend = CloudEmbeddingBackend("text-embedding-3-small")

        with patch.object(backend, "_call_provider", new_callable=AsyncMock, return_value=[[0.1]]) as mock_call:
            await backend.embed_texts(["test"])
            mock_call.assert_called_once_with(["test"], None)

    async def test_embed_texts_dimensions_fallback(self):
        """Falls back to local truncation when provider rejects dimensions param."""
        backend = CloudEmbeddingBackend("embed-multilingual-v3.0")

        unsupported_err = Exception("output_dimension is not supported for this model")

        with patch.object(backend, "_call_provider", new_callable=AsyncMock,
            side_effect=[unsupported_err, [[0.1] * 1024]],
        ):
            result = await backend.embed_texts(["test"], dimensions=768)
            # Should truncate locally to 768
            assert len(result[0]) == 768

    async def test_embed_texts_local_truncation(self):
        """Truncates locally when server returns more dims than requested."""
        backend = CloudEmbeddingBackend("gemini/gemini-embedding-001")

        with patch.object(backend, "_call_provider", new_callable=AsyncMock, return_value=[[0.1] * 3072]):
            result = await backend.embed_texts(["test"], dimensions=768)
            assert len(result[0]) == 768

    async def test_embed_texts_api_error(self):
        """Non-retryable API errors are raised to caller."""
        backend = CloudEmbeddingBackend("text-embedding-3-small")

        with patch.object(backend, "_call_provider", new_callable=AsyncMock, side_effect=Exception("Invalid model"),
        ):
            with pytest.raises(Exception, match="Invalid model"):
                await backend.embed_texts(["test"])

    async def test_embed_single_success(self):
        """Single text embedding returns one vector."""
        backend = CloudEmbeddingBackend("text-embedding-3-small")

        with patch.object(backend, "_call_provider", new_callable=AsyncMock, return_value=[[0.1, 0.2, 0.3]]):
            vec = await backend.embed_single("hello")

        assert vec == [0.1, 0.2, 0.3]

    async def test_check_available(self):
        """Returns dimension count when model is available."""
        backend = CloudEmbeddingBackend("text-embedding-3-small")

        with patch.object(backend, "_call_provider", new_callable=AsyncMock, return_value=[[0.0] * 768]):
            dims = await backend.check_available()

        assert dims == 768

    async def test_check_unavailable(self):
        """Returns 0 when model is not available."""
        backend = CloudEmbeddingBackend("nonexistent")

        with patch.object(backend, "_call_provider", new_callable=AsyncMock, side_effect=Exception("Invalid API key")
        ):
            dims = await backend.check_available()

        assert dims == 0


# -----------------------------------------------------------------------
# CloudEmbeddingBackend: Provider-specific SDK mocks
# -----------------------------------------------------------------------


class TestProviderSDKs:
    """Test that each provider SDK is called correctly."""

    async def test_embed_openai(self):
        """OpenAI SDK is called with correct params."""
        backend = CloudEmbeddingBackend("text-embedding-3-small", api_key="test-key")

        mock_embedding = MagicMock()
        mock_embedding.index = 0
        mock_embedding.embedding = [0.1, 0.2, 0.3]

        mock_response = MagicMock()
        mock_response.data = [mock_embedding]

        mock_client = MagicMock()
        mock_client.embeddings.create.return_value = mock_response

        mock_openai_cls = MagicMock(return_value=mock_client)
        mock_openai_mod = MagicMock(OpenAI=mock_openai_cls)

        with patch.dict("sys.modules", {"openai": mock_openai_mod}):
            result = backend._embed_openai(["test"])
            mock_openai_cls.assert_called_once_with(
                api_key="test-key", base_url="https://api.openai.com/v1"
            )
            mock_client.embeddings.create.assert_called_once_with(
                model="text-embedding-3-small", input=["test"]
            )

        assert result == [[0.1, 0.2, 0.3]]

    async def test_embed_openai_with_dimensions(self):
        """OpenAI passes dimensions param."""
        backend = CloudEmbeddingBackend("text-embedding-3-small", api_key="test-key")

        mock_embedding = MagicMock()
        mock_embedding.index = 0
        mock_embedding.embedding = [0.1]

        mock_response = MagicMock()
        mock_response.data = [mock_embedding]

        mock_client = MagicMock()
        mock_client.embeddings.create.return_value = mock_response

        mock_openai_cls = MagicMock(return_value=mock_client)
        mock_openai_mod = MagicMock(OpenAI=mock_openai_cls)

        with patch.dict("sys.modules", {"openai": mock_openai_mod}):
            backend._embed_openai(["test"], dimensions=256)
            mock_client.embeddings.create.assert_called_once_with(
                model="text-embedding-3-small", input=["test"], dimensions=256
            )

    async def test_embed_openai_with_api_base(self):
        """OpenAI uses custom api_base."""
        backend = CloudEmbeddingBackend(
            "text-embedding-3-small",
            api_key="test-key",
            api_base="https://custom.api/v1",
        )

        mock_embedding = MagicMock()
        mock_embedding.index = 0
        mock_embedding.embedding = [0.1]

        mock_response = MagicMock()
        mock_response.data = [mock_embedding]

        mock_client = MagicMock()
        mock_client.embeddings.create.return_value = mock_response

        mock_openai_cls = MagicMock(return_value=mock_client)
        mock_openai_mod = MagicMock(OpenAI=mock_openai_cls)

        with patch.dict("sys.modules", {"openai": mock_openai_mod}):
            backend._embed_openai(["test"])
            mock_openai_cls.assert_called_once_with(
                api_key="test-key", base_url="https://custom.api/v1"
            )

    async def test_embed_cohere(self):
        """Cohere SDK (ClientV2) is called with correct params."""
        backend = CloudEmbeddingBackend("embed-multilingual-v3.0", api_key="test-key")

        mock_embeddings = MagicMock()
        mock_embeddings.float_ = [[0.1, 0.2, 0.3]]

        mock_response = MagicMock()
        mock_response.embeddings = mock_embeddings

        mock_client = MagicMock()
        mock_client.embed.return_value = mock_response

        mock_cohere_mod = MagicMock()
        mock_cohere_mod.ClientV2.return_value = mock_client

        with patch.dict("sys.modules", {"cohere": mock_cohere_mod}):
            result = backend._embed_cohere(["test"])
            mock_cohere_mod.ClientV2.assert_called_once_with(api_key="test-key")
            mock_client.embed.assert_called_once_with(
                model="embed-multilingual-v3.0",
                texts=["test"],
                input_type="search_document",
                embedding_types=["float"],
                truncate="END",
            )

        assert result == [[0.1, 0.2, 0.3]]

    async def test_embed_cohere_truncates_locally(self):
        """Cohere truncates locally when dimensions requested."""
        backend = CloudEmbeddingBackend("embed-multilingual-v3.0", api_key="test-key")

        mock_embeddings = MagicMock()
        mock_embeddings.float_ = [[0.1] * 1024]

        mock_response = MagicMock()
        mock_response.embeddings = mock_embeddings

        mock_client = MagicMock()
        mock_client.embed.return_value = mock_response

        mock_cohere_mod = MagicMock()
        mock_cohere_mod.ClientV2.return_value = mock_client

        with patch.dict("sys.modules", {"cohere": mock_cohere_mod}):
            result = backend._embed_cohere(["test"], dimensions=768)

        assert len(result[0]) == 768

    async def test_embed_gemini(self):
        """Gemini SDK is called with correct params."""
        backend = CloudEmbeddingBackend(
            "gemini/gemini-embedding-001", api_key="test-key"
        )

        mock_embedding = MagicMock()
        mock_embedding.values = [0.1, 0.2, 0.3]

        mock_result = MagicMock()
        mock_result.embeddings = [mock_embedding]

        mock_client = MagicMock()
        mock_client.models.embed_content.return_value = mock_result

        mock_genai = MagicMock()
        mock_genai.Client.return_value = mock_client

        mock_google = MagicMock()
        mock_google.genai = mock_genai

        with patch.dict(
            "sys.modules",
            {
                "google": mock_google,
                "google.genai": mock_genai,
                "google.genai.types": MagicMock(),
            },
        ):
            result = backend._embed_gemini(["test"])
            mock_genai.Client.assert_called_once_with(api_key="test-key")

        assert result == [[0.1, 0.2, 0.3]]

    async def test_embed_jina(self):
        """Jina AI REST API is called with correct params."""
        backend = CloudEmbeddingBackend(
            "jina_ai/jina-embeddings-v3", api_key="test-key"
        )

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "data": [{"index": 0, "embedding": [0.1, 0.2, 0.3]}]
        }
        mock_response.raise_for_status = MagicMock()

        mock_httpx = MagicMock()
        mock_httpx.post.return_value = mock_response

        with patch.dict("sys.modules", {"httpx": mock_httpx}):
            result = backend._embed_jina(["test"])

        assert result == [[0.1, 0.2, 0.3]]


# -----------------------------------------------------------------------
# CloudEmbeddingBackend: Batch splitting
# -----------------------------------------------------------------------


class TestBatchSplitting:
    async def test_splits_large_batch(self):
        """Texts exceeding MAX_BATCH_SIZE are split into sub-batches."""
        backend = CloudEmbeddingBackend("text-embedding-3-small")
        n = backend.MAX_BATCH_SIZE + 50  # 150 texts -> 2 batches

        def mock_call(texts, dimensions=None):
            return [[float(j)] for j in range(len(texts))]

        with patch.object(backend, "_call_provider", new_callable=AsyncMock, side_effect=mock_call):
            vecs = await backend.embed_texts([f"text_{i}" for i in range(n)])

        assert len(vecs) == n

    async def test_batch_call_count(self):
        """Correct number of API calls for split batches."""
        backend = CloudEmbeddingBackend("text-embedding-3-small")
        n = backend.MAX_BATCH_SIZE * 2 + 10  # 210 texts -> 3 batches

        def mock_call(texts, dimensions=None):
            return [[0.0] for _ in range(len(texts))]

        with patch.object(backend, "_call_provider", new_callable=AsyncMock, side_effect=mock_call) as mock:
            await backend.embed_texts([f"t{i}" for i in range(n)])

        assert mock.call_count == 3

    async def test_no_split_under_limit(self):
        """No splitting when under MAX_BATCH_SIZE."""
        backend = CloudEmbeddingBackend("text-embedding-3-small")
        n = backend.MAX_BATCH_SIZE

        def mock_call(texts, dimensions=None):
            return [[0.0] for _ in range(len(texts))]

        with patch.object(backend, "_call_provider", new_callable=AsyncMock, side_effect=mock_call) as mock:
            await backend.embed_texts([f"text_{i}" for i in range(n)])

        assert mock.call_count == 1


# -----------------------------------------------------------------------
# CloudEmbeddingBackend: Retry logic
# -----------------------------------------------------------------------


class TestRetryLogic:
    @patch("wet_mcp.embedder.asyncio.sleep", new_callable=AsyncMock)
    async def test_retries_on_rate_limit(self, mock_sleep):
        """Retries on rate limit errors with exponential backoff."""
        backend = CloudEmbeddingBackend("text-embedding-3-small")

        with patch.object(backend, "_call_provider", new_callable=AsyncMock,
            side_effect=[
                Exception("429 rate limit exceeded"),
                [[0.1]],
            ],
        ):
            result = await backend.embed_texts(["test"])

        assert result == [[0.1]]
        mock_sleep.assert_called_once_with(1.0)

    @patch("wet_mcp.embedder.asyncio.sleep", new_callable=AsyncMock)
    async def test_retries_on_server_error(self, mock_sleep):
        """Retries on 5xx server errors."""
        backend = CloudEmbeddingBackend("text-embedding-3-small")

        with patch.object(backend, "_call_provider", new_callable=AsyncMock,
            side_effect=[
                Exception("503 service temporarily unavailable"),
                [[0.2]],
            ],
        ):
            result = await backend.embed_texts(["test"])

        assert result == [[0.2]]

    @patch("wet_mcp.embedder.asyncio.sleep", new_callable=AsyncMock)
    async def test_no_retry_on_non_retryable(self, mock_sleep):
        """Non-retryable errors fail immediately without retry."""
        backend = CloudEmbeddingBackend("text-embedding-3-small")

        with patch.object(backend, "_call_provider", new_callable=AsyncMock,
            side_effect=Exception("Invalid API key"),
        ):
            with pytest.raises(Exception, match="Invalid API key"):
                await backend.embed_texts(["test"])

        mock_sleep.assert_not_called()

    @patch("wet_mcp.embedder.asyncio.sleep", new_callable=AsyncMock)
    async def test_exponential_backoff(self, mock_sleep):
        """Retry delays use exponential backoff."""
        backend = CloudEmbeddingBackend("text-embedding-3-small")

        with patch.object(backend, "_call_provider", new_callable=AsyncMock,
            side_effect=[
                Exception("429 rate limit"),
                Exception("429 rate limit"),
                [[0.1]],
            ],
        ):
            await backend.embed_texts(["test"])

        assert mock_sleep.call_args_list == [call(1.0), call(2.0)]

    @patch("wet_mcp.embedder.asyncio.sleep", new_callable=AsyncMock)
    async def test_max_retries_exhausted(self, mock_sleep):
        """Raises after all retries are exhausted."""
        backend = CloudEmbeddingBackend("text-embedding-3-small")

        with patch.object(backend, "_call_provider", new_callable=AsyncMock,
            side_effect=Exception("429 rate limit"),
        ):
            with pytest.raises(Exception, match="429 rate limit"):
                await backend.embed_texts(["test"])

        # 3 attempts total, 2 sleeps
        assert mock_sleep.call_count == 2


# -----------------------------------------------------------------------
# Qwen3EmbedBackend
# -----------------------------------------------------------------------


class TestQwen3EmbedBackend:
    async def test_embed_texts_success(self):
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
            vecs = await backend.embed_texts(["hello", "world"])

        assert len(vecs) == 2
        assert vecs[0] == pytest.approx([0.1, 0.2, 0.3])
        assert vecs[1] == pytest.approx([0.4, 0.5, 0.6])

    async def test_embed_texts_empty(self):
        """Empty input returns empty list."""
        backend = Qwen3EmbedBackend()
        assert await backend.embed_texts([]) == []

    async def test_embed_texts_with_mrl_truncation(self):
        """Dimensions parameter is passed to model.embed(dim=) for MRL."""
        import numpy as np

        backend = Qwen3EmbedBackend()
        mock_model = MagicMock()
        # Model handles truncation internally when dim= is passed
        mock_model.embed.return_value = iter(
            [
                np.array([0.1, 0.2, 0.3]),
            ]
        )

        with patch.object(backend, "_get_model", return_value=mock_model):
            vecs = await backend.embed_texts(["test"], dimensions=3)

        mock_model.embed.assert_called_once_with(["test"], dim=3)
        assert len(vecs[0]) == 3
        assert vecs[0] == pytest.approx([0.1, 0.2, 0.3])

    async def test_embed_single(self):
        """embed_single delegates to embed_texts."""
        import numpy as np

        backend = Qwen3EmbedBackend()
        mock_model = MagicMock()
        mock_model.embed.return_value = iter([np.array([0.1, 0.2])])

        with patch.object(backend, "_get_model", return_value=mock_model):
            vec = await backend.embed_single("test")

        assert vec == pytest.approx([0.1, 0.2])

    async def test_check_available_success(self):
        """Returns dimensions when model loads successfully."""
        import numpy as np

        backend = Qwen3EmbedBackend()
        mock_model = MagicMock()
        mock_model.embed.return_value = iter([np.array([0.0] * 1024)])

        with patch.object(backend, "_get_model", return_value=mock_model):
            dims = await backend.check_available()

        assert dims == 1024

    async def test_check_available_failure(self):
        """Returns 0 when model fails to load."""
        backend = Qwen3EmbedBackend()

        with patch.object(
            backend, "_get_model", side_effect=Exception("ONNX load error")
        ):
            dims = await backend.check_available()

        assert dims == 0


# -----------------------------------------------------------------------
# Factory functions
# -----------------------------------------------------------------------


class TestBackendFactory:
    async def test_init_cloud_backend(self):
        """init_backend('cloud') creates CloudEmbeddingBackend."""
        backend = init_backend("cloud", "test-model")
        assert isinstance(backend, CloudEmbeddingBackend)
        assert get_backend() is backend

    async def test_init_local_backend(self):
        """init_backend('local') creates Qwen3EmbedBackend."""
        backend = init_backend("local")
        assert isinstance(backend, Qwen3EmbedBackend)
        assert get_backend() is backend

    async def test_init_cloud_requires_model(self):
        """Cloud backend requires model name."""
        with pytest.raises(ValueError, match="model is required"):
            init_backend("cloud")

    async def test_init_unknown_backend(self):
        """Unknown backend type raises ValueError."""
        with pytest.raises(ValueError, match="Unknown backend"):
            init_backend("unknown")


# -----------------------------------------------------------------------
# check_available: API key validation messages
# -----------------------------------------------------------------------


class TestCheckAvailableApiKeyValidation:
    """check_available() distinguishes API key errors from other failures."""

    async def test_api_key_401_returns_zero(self):
        """401 errors are caught and return 0."""
        backend = CloudEmbeddingBackend("text-embedding-3-small")
        with patch.object(backend, "_call_provider", new_callable=AsyncMock, side_effect=Exception("401 Unauthorized")
        ):
            assert await backend.check_available() == 0

    async def test_api_key_403_returns_zero(self):
        """403 forbidden returns 0."""
        backend = CloudEmbeddingBackend("text-embedding-3-small")
        with patch.object(backend, "_call_provider", new_callable=AsyncMock, side_effect=Exception("403 Forbidden")
        ):
            assert await backend.check_available() == 0

    async def test_invalid_key_detected(self):
        """'invalid' keyword in error is caught."""
        backend = CloudEmbeddingBackend("text-embedding-3-small")
        with patch.object(backend, "_call_provider", new_callable=AsyncMock,
            side_effect=Exception("Invalid API key provided"),
        ):
            assert await backend.check_available() == 0

    async def test_unauthorized_detected(self):
        """'unauthorized' keyword in error is caught."""
        backend = CloudEmbeddingBackend("text-embedding-3-small")
        with patch.object(backend, "_call_provider", new_callable=AsyncMock,
            side_effect=Exception("Unauthorized access"),
        ):
            assert await backend.check_available() == 0

    async def test_non_auth_error_returns_zero(self):
        """Non-auth errors (e.g. model not found) also return 0."""
        backend = CloudEmbeddingBackend("text-embedding-3-small")
        with patch.object(backend, "_call_provider", new_callable=AsyncMock,
            side_effect=Exception("Model not found"),
        ):
            assert await backend.check_available() == 0

    async def test_success_returns_dims(self):
        """Successful check returns embedding dimensions."""
        backend = CloudEmbeddingBackend("text-embedding-3-small")
        with patch.object(backend, "_call_provider", new_callable=AsyncMock, return_value=[[0.1, 0.2, 0.3]]):
            assert await backend.check_available() == 3

    async def test_empty_embeddings_returns_zero(self):
        """Returns 0 when provider returns empty embeddings."""
        backend = CloudEmbeddingBackend("text-embedding-3-small")
        with patch.object(backend, "_call_provider", new_callable=AsyncMock, return_value=[]):
            assert await backend.check_available() == 0


# -----------------------------------------------------------------------
# Qwen3 model loading edge cases
# -----------------------------------------------------------------------


class TestQwen3GetModelWarning:
    """_get_model() logs download warning and check_available edge cases."""

    async def test_check_available_import_error(self):
        """Returns 0 when qwen3-embed is not installed."""
        backend = Qwen3EmbedBackend()
        with patch.object(backend, "_get_model", side_effect=ImportError("No module")):
            assert await backend.check_available() == 0

    async def test_check_available_success(self):
        """Returns dims when local model works."""
        import numpy as np

        backend = Qwen3EmbedBackend()
        mock_model = MagicMock()
        mock_model.embed.return_value = iter([np.array([0.1, 0.2, 0.3])])
        with patch.object(backend, "_get_model", return_value=mock_model):
            assert await backend.check_available() == 3
