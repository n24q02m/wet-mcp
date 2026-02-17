"""Dual-backend embedding: LiteLLM (cloud) + qwen3-embed (local ONNX).

Supports two backends:
- **litellm**: Cloud providers via LiteLLM (OpenAI, Gemini, Mistral, Cohere).
  Requires API keys. Auto-detects provider from API_KEYS config.
- **local**: Local ONNX inference via qwen3-embed (Qwen3-Embedding-0.6B).
  No API keys needed, ~0.57GB model download on first use.

Backend selection is auto-detected in config.resolve_embedding_backend():
1. Explicit EMBEDDING_BACKEND env var
2. 'local' if qwen3-embed is installed
3. 'litellm' if API keys are configured
4. '' (no embedding, FTS5-only search)

Embeddings are truncated to fixed dims in server._embed().
"""

from __future__ import annotations

import logging
import os
import time
from typing import Protocol

from loguru import logger

# ---------------------------------------------------------------------------
# Shared constants
# ---------------------------------------------------------------------------

# Retry config for transient errors (rate limits, 5xx, network).
MAX_RETRIES = 3
RETRY_BASE_DELAY = 1.0  # seconds, doubles each retry


def _is_retryable(exc: Exception) -> bool:
    """Check if an exception is transient and worth retrying."""
    msg = str(exc).lower()
    retryable_patterns = [
        "rate limit",
        "rate_limit",
        "429",
        "quota",
        "too many requests",
        "500",
        "502",
        "503",
        "504",
        "timeout",
        "timed out",
        "connection",
        "temporarily unavailable",
        "overloaded",
        "resource exhausted",
        "resource_exhausted",
    ]
    return any(p in msg for p in retryable_patterns)


# ---------------------------------------------------------------------------
# Backend Protocol
# ---------------------------------------------------------------------------


class EmbeddingBackend(Protocol):
    """Protocol for embedding backends."""

    def embed_texts(
        self,
        texts: list[str],
        dimensions: int | None = None,
    ) -> list[list[float]]:
        """Embed a batch of texts. Returns list of embedding vectors."""
        ...

    def embed_single(
        self,
        text: str,
        dimensions: int | None = None,
    ) -> list[float]:
        """Embed a single text. Returns embedding vector."""
        ...

    def check_available(self) -> int:
        """Check if backend is available.

        Returns:
            Embedding dimensions if available, 0 if not.
        """
        ...


# ---------------------------------------------------------------------------
# LiteLLM Backend (cloud)
# ---------------------------------------------------------------------------


class LiteLLMBackend:
    """Cloud embedding via LiteLLM (OpenAI, Gemini, Mistral, Cohere)."""

    # Gemini API: max 100 texts per batch request.
    # Other providers (OpenAI, Cohere) allow more but 100 is safe for all.
    MAX_BATCH_SIZE = 100

    def __init__(self, model: str):
        self.model = model
        self._setup_litellm()

    def _setup_litellm(self) -> None:
        """Silence LiteLLM logging."""
        os.environ.setdefault("LITELLM_LOG", "ERROR")
        import litellm

        litellm.suppress_debug_info = True  # type: ignore[assignment]
        litellm.set_verbose = False
        logging.getLogger("LiteLLM").setLevel(logging.ERROR)
        logging.getLogger("LiteLLM").handlers = [logging.NullHandler()]

    def _embed_batch_inner(
        self,
        texts: list[str],
        dimensions: int | None = None,
    ) -> list[list[float]]:
        """Embed a single batch with retry logic for transient errors."""
        from litellm import embedding as litellm_embedding

        kwargs: dict = {
            "model": self.model,
            "input": texts,
        }
        if dimensions:
            kwargs["dimensions"] = dimensions

        last_exc: Exception | None = None
        for attempt in range(MAX_RETRIES):
            try:
                response = litellm_embedding(**kwargs)
                data = sorted(response.data, key=lambda x: x["index"])
                return [d["embedding"] for d in data]
            except Exception as e:
                last_exc = e
                if attempt < MAX_RETRIES - 1 and _is_retryable(e):
                    delay = RETRY_BASE_DELAY * (2**attempt)
                    logger.warning(
                        f"Embedding retry {attempt + 1}/{MAX_RETRIES} "
                        f"after {delay}s: {e}"
                    )
                    time.sleep(delay)
                else:
                    break

        logger.error(f"Embedding failed ({self.model}): {last_exc}")
        raise last_exc  # type: ignore[misc]

    def embed_texts(
        self,
        texts: list[str],
        dimensions: int | None = None,
    ) -> list[list[float]]:
        """Embed texts with auto batch splitting."""
        if not texts:
            return []

        if len(texts) <= self.MAX_BATCH_SIZE:
            return self._embed_batch_inner(texts, dimensions)

        # Split into batches
        all_embeddings: list[list[float]] = []
        total_batches = (len(texts) + self.MAX_BATCH_SIZE - 1) // self.MAX_BATCH_SIZE
        logger.info(
            f"Splitting {len(texts)} texts into {total_batches} batches "
            f"(max {self.MAX_BATCH_SIZE}/batch)"
        )

        for i in range(0, len(texts), self.MAX_BATCH_SIZE):
            batch = texts[i : i + self.MAX_BATCH_SIZE]
            batch_num = i // self.MAX_BATCH_SIZE + 1
            logger.debug(
                f"Embedding batch {batch_num}/{total_batches}: {len(batch)} texts"
            )
            batch_result = self._embed_batch_inner(batch, dimensions)
            all_embeddings.extend(batch_result)

        return all_embeddings

    def embed_single(
        self,
        text: str,
        dimensions: int | None = None,
    ) -> list[float]:
        """Embed a single text."""
        results = self.embed_texts([text], dimensions)
        return results[0]

    def check_available(self) -> int:
        """Check if the LiteLLM model is available via test request."""
        try:
            from litellm import embedding as litellm_embedding

            response = litellm_embedding(model=self.model, input=["test"])
            if response.data:
                dim = len(response.data[0]["embedding"])
                logger.info(f"Embedding model {self.model} available (dims={dim})")
                return dim
            return 0
        except Exception as e:
            logger.debug(f"Embedding model {self.model} not available: {e}")
            return 0


# ---------------------------------------------------------------------------
# qwen3-embed Backend (local ONNX)
# ---------------------------------------------------------------------------


class Qwen3EmbedBackend:
    """Local ONNX embedding via qwen3-embed (Qwen3-Embedding-0.6B).

    Uses last-token pooling with instruction-aware queries.
    Model is downloaded on first use (~0.57GB).
    Batch size is forced to 1 (static ONNX graph).
    """

    # Default model for qwen3-embed
    DEFAULT_MODEL = "Qwen/Qwen3-Embedding-0.6B"

    def __init__(self, model_name: str | None = None):
        self._model_name = model_name or self.DEFAULT_MODEL
        self._model = None

    def _get_model(self):
        """Lazy-load the embedding model."""
        if self._model is None:
            from qwen3_embed import TextEmbedding

            logger.info(f"Loading local embedding model: {self._model_name}")
            self._model = TextEmbedding(model_name=self._model_name)
            logger.info("Local embedding model loaded")
        return self._model

    def embed_texts(
        self,
        texts: list[str],
        dimensions: int | None = None,
    ) -> list[list[float]]:
        """Embed texts using local ONNX model."""
        if not texts:
            return []

        model = self._get_model()
        # Pass dim to model.embed() so MRL truncation happens BEFORE L2-normalization
        kwargs = {}
        if dimensions and dimensions > 0:
            kwargs["dim"] = dimensions
        embeddings = list(model.embed(texts, **kwargs))
        return [emb.tolist() for emb in embeddings]

    def embed_single(
        self,
        text: str,
        dimensions: int | None = None,
    ) -> list[float]:
        """Embed a single text (document/passage)."""
        results = self.embed_texts([text], dimensions)
        return results[0]

    def embed_single_query(
        self,
        text: str,
        dimensions: int | None = None,
    ) -> list[float]:
        """Embed a query with instruction prefix (asymmetric retrieval)."""
        model = self._get_model()
        kwargs = {}
        if dimensions and dimensions > 0:
            kwargs["dim"] = dimensions
        result = list(model.query_embed(text, **kwargs))
        return result[0].tolist()

    def check_available(self) -> int:
        """Check if qwen3-embed is available."""
        try:
            model = self._get_model()
            result = list(model.embed(["test"]))
            if result:
                dim = len(result[0])
                logger.info(
                    f"Local embedding {self._model_name} available (dims={dim})"
                )
                return dim
            return 0
        except Exception as e:
            logger.warning(f"Local embedding not available: {e}")
            return 0


# ---------------------------------------------------------------------------
# Factory + module-level convenience functions
# ---------------------------------------------------------------------------

_backend: EmbeddingBackend | None = None


def get_backend() -> EmbeddingBackend | None:
    """Get the current embedding backend singleton."""
    return _backend


def init_backend(backend_type: str, model: str | None = None) -> EmbeddingBackend:
    """Initialize and cache the embedding backend.

    Args:
        backend_type: 'litellm' or 'local'
        model: Model name (required for litellm, optional for local)

    Returns:
        Initialized backend instance.
    """
    global _backend

    if backend_type == "litellm":
        if not model:
            raise ValueError("model is required for litellm backend")
        _backend = LiteLLMBackend(model)
    elif backend_type == "local":
        _backend = Qwen3EmbedBackend(model)
    else:
        raise ValueError(f"Unknown backend type: {backend_type}")

    return _backend


# Legacy module-level functions for backward compatibility
def embed_texts(
    texts: list[str],
    model: str,
    dimensions: int | None = None,
) -> list[list[float]]:
    """Embed texts using LiteLLM (legacy interface).

    Kept for backward compatibility. Prefer using backend instances directly.
    """
    backend = LiteLLMBackend(model)
    return backend.embed_texts(texts, dimensions)


def embed_single(
    text: str,
    model: str,
    dimensions: int | None = None,
) -> list[float]:
    """Embed a single text (legacy interface)."""
    backend = LiteLLMBackend(model)
    return backend.embed_single(text, dimensions)


def check_embedding_available(model: str) -> int:
    """Check if an embedding model is available (legacy interface)."""
    backend = LiteLLMBackend(model)
    return backend.check_available()
