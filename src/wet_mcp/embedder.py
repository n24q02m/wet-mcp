"""Dual-backend embedding: Cloud (native SDKs) + qwen3-embed (local).

Supports two backends:
- **cloud**: Cloud providers via native SDKs (Google Gemini, OpenAI, Cohere).
  Requires API keys. Auto-detects provider from API_KEYS config.
- **local**: Local inference via qwen3-embed. GGUF if GPU + llama-cpp-python,
  ONNX otherwise. No API keys needed, ~0.5GB model download on first use.

Backend selection (always returns a valid backend):
1. Explicit EMBEDDING_BACKEND env var
2. 'cloud' if API keys are configured
3. 'local' (default, always available)

Embeddings are truncated to fixed dims in server._embed().
"""

import asyncio
import os
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
        "unavailable",
        "overloaded",
    ]
    return any(p in msg for p in retryable_patterns)


def _is_unsupported_param(exc: Exception, param: str) -> bool:
    """Check if the error is due to an unsupported parameter."""
    msg = str(exc).lower()
    # "dimensions" parameter is the primary one we care about for fallback
    if param == "dimensions":
        return any(
            p in msg
            for p in (
                "dimensions",
                "output_dimension",
                "output_dimensionality",
                "unexpected keyword argument",
                "invalid argument",
                "unsupported parameter",
            )
        )
    return False


# ---------------------------------------------------------------------------
# Backend Protocol
# ---------------------------------------------------------------------------


class EmbeddingBackend(Protocol):
    """Protocol for embedding backends."""

    async def embed_texts(
        self,
        texts: list[str],
        dimensions: int | None = None,
    ) -> list[list[float]]:
        """Embed a batch of texts. Returns list of embedding vectors."""
        ...  # pragma: no cover

    async def embed_single(
        self,
        text: str,
        dimensions: int | None = None,
    ) -> list[float]:
        """Embed a single text. Returns embedding vector."""
        ...  # pragma: no cover

    async def check_available(self) -> int:
        """Check if backend is available.

        Returns:
            Embedding dimensions if available, 0 if not.
        """
        ...  # pragma: no cover


# ---------------------------------------------------------------------------
# Provider detection for embedding models
# ---------------------------------------------------------------------------


def _detect_embedding_provider(model: str) -> str:
    """Detect provider from model name.

    Returns 'gemini', 'openai', 'cohere', or 'jina'.
    """
    lower = model.lower()
    if lower.startswith("gemini/") or "gemini" in lower:
        return "gemini"
    if lower.startswith("jina_ai/") or lower.startswith("jina"):
        return "jina"
    if lower.startswith("embed-") or lower.startswith("cohere/"):
        return "cohere"
    # text-embedding-3-large, text-embedding-ada-002, etc.
    if lower.startswith("text-embedding") or lower.startswith("openai/"):
        return "openai"
    # Default fallback: check env vars
    if os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY"):
        return "gemini"
    if os.getenv("OPENAI_API_KEY"):
        return "openai"
    if os.getenv("COHERE_API_KEY"):
        return "cohere"
    return "openai"


def _strip_provider(model: str) -> str:
    """Strip provider prefix (e.g. 'gemini/model' -> 'model')."""
    if "/" in model:
        return model.split("/", 1)[1]
    return model


# ---------------------------------------------------------------------------
# Cloud Backend (native SDKs)
# ---------------------------------------------------------------------------


class CloudEmbeddingBackend:
    """Cloud embedding via native SDKs (Gemini, OpenAI, Cohere)."""

    MAX_BATCH_SIZE = 96  # Common safe batch size across providers

    def __init__(
        self,
        model: str,
        api_base: str | None = None,
        api_key: str | None = None,
    ):
        self.model = model
        self.api_base = api_base
        self.api_key = api_key
        self._provider = _detect_embedding_provider(model)
        self._bare_model = _strip_provider(model)

    async def _embed_batch_inner(
        self,
        texts: list[str],
        dimensions: int | None = None,
    ) -> list[list[float]]:
        """Embed a single batch with retry logic for transient errors.

        Tries server-side MRL truncation first (``dimensions`` param).
        If the provider rejects ``dimensions``, retries without it and
        truncates locally. This ensures Gemini, Cohere, and other
        providers that don't support ``dimensions`` still work.
        """
        use_dimensions = dimensions
        last_exc: Exception | None = None

        for attempt in range(MAX_RETRIES):
            try:
                embeddings = await self._call_provider(texts, use_dimensions)
                # Truncate locally if server returned more dims than requested
                if dimensions and embeddings and len(embeddings[0]) > dimensions:
                    embeddings = [e[:dimensions] for e in embeddings]
                return embeddings
            except Exception as e:
                # If the provider rejects `dimensions`, retry without it
                if (
                    use_dimensions
                    and not _is_retryable(e)
                    and _is_unsupported_param(e, "dimensions")
                ):
                    logger.debug(
                        f"Provider does not support dimensions param, "
                        f"will truncate locally: {e}"
                    )
                    use_dimensions = None
                    continue

                last_exc = e
                if attempt < MAX_RETRIES - 1 and _is_retryable(e):
                    delay = RETRY_BASE_DELAY * (2**attempt)
                    logger.warning(
                        f"Embedding retry {attempt + 1}/{MAX_RETRIES} "
                        f"after {delay}s: {e}"
                    )
                    await asyncio.sleep(delay)
                else:
                    break

        logger.error(f"Embedding failed ({self.model}): {last_exc}")
        assert last_exc is not None  # guaranteed by loop logic
        raise last_exc

    async def _call_provider(
        self, texts: list[str], dimensions: int | None = None
    ) -> list[list[float]]:
        """Route to the correct provider SDK."""
        if self._provider == "gemini":
            return await self._embed_gemini(texts, dimensions)
        elif self._provider == "cohere":
            return await self._embed_cohere(texts, dimensions)
        elif self._provider == "jina":
            return await self._embed_jina(texts, dimensions)
        else:
            return await self._embed_openai(texts, dimensions)

    async def _embed_gemini(
        self, texts: list[str], dimensions: int | None = None
    ) -> list[list[float]]:
        """Embed via Gemini SDK (google-genai)."""
        from google import genai
        from google.genai import types

        key = (
            self.api_key
            or os.getenv("GEMINI_API_KEY")
            or os.getenv("GOOGLE_API_KEY")
            or ""
        )
        client = genai.Client(api_key=key)

        config_kwargs: dict = {}
        if dimensions:
            config_kwargs["output_dimensionality"] = dimensions

        # google-genai Client.models.embed_content is synchronous, use to_thread
        result = await asyncio.to_thread(
            client.models.embed_content,
            model=self._bare_model,
            contents=texts,  # type: ignore[invalid-argument-type]  # ty: ignore[invalid-argument-type]  # SDK accepts list[str]
            config=types.EmbedContentConfig(**config_kwargs) if config_kwargs else None,
        )

        embeddings = result.embeddings or []
        return [list(e.values or []) for e in embeddings]

    async def _embed_openai(
        self, texts: list[str], dimensions: int | None = None
    ) -> list[list[float]]:
        """Embed via OpenAI SDK."""
        from openai import AsyncOpenAI

        key = self.api_key or os.getenv("OPENAI_API_KEY") or ""
        base = self.api_base or "https://api.openai.com/v1"
        client = AsyncOpenAI(api_key=key, base_url=base)

        kwargs: dict = {
            "model": self._bare_model,
            "input": texts,
        }
        if dimensions:
            kwargs["dimensions"] = dimensions

        response = await client.embeddings.create(**kwargs)
        data = sorted(response.data, key=lambda x: x.index)
        return [d.embedding for d in data]

    async def _embed_cohere(
        self, texts: list[str], dimensions: int | None = None
    ) -> list[list[float]]:
        """Embed via Cohere SDK (ClientV2)."""
        import cohere

        key = self.api_key or os.getenv("COHERE_API_KEY") or ""
        # Cohere V2 SDK's ClientV2.embed is synchronous, use to_thread
        client = cohere.ClientV2(api_key=key)

        response = await asyncio.to_thread(
            client.embed,
            model=self._bare_model,
            texts=texts,
            input_type="search_document",
            embedding_types=["float"],
            truncate="END",
        )

        raw = response.embeddings.float_ or []
        embeddings = [list(e) for e in raw]
        # Truncate locally if dimensions requested (Cohere doesn't support it natively)
        if dimensions and embeddings and len(embeddings[0]) > dimensions:
            embeddings = [e[:dimensions] for e in embeddings]
        return embeddings

    async def _embed_jina(
        self, texts: list[str], dimensions: int | None = None
    ) -> list[list[float]]:
        """Embed via Jina AI (httpx, REST API)."""
        import httpx

        key = self.api_key or os.getenv("JINA_AI_API_KEY") or ""
        payload: dict = {
            "model": self._bare_model,
            "input": texts,
        }
        if dimensions:
            payload["dimensions"] = dimensions

        async with httpx.AsyncClient() as client:
            response = await client.post(
                "https://api.jina.ai/v1/embeddings",
                json=payload,
                headers={
                    "Authorization": f"Bearer {key}",
                    "Content-Type": "application/json",
                },
                timeout=60,
            )
            response.raise_for_status()
            data = response.json()["data"]
            data_sorted = sorted(data, key=lambda x: x["index"])
            return [d["embedding"] for d in data_sorted]

    async def embed_texts(
        self,
        texts: list[str],
        dimensions: int | None = None,
    ) -> list[list[float]]:
        """Embed texts with auto batch splitting."""
        if not texts:
            return []

        if len(texts) <= self.MAX_BATCH_SIZE:
            return await self._embed_batch_inner(texts, dimensions)

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
            batch_result = await self._embed_batch_inner(batch, dimensions)
            all_embeddings.extend(batch_result)

        return all_embeddings

    async def embed_single(
        self,
        text: str,
        dimensions: int | None = None,
    ) -> list[float]:
        """Embed a single text."""
        results = await self.embed_texts([text], dimensions)
        return results[0]

    async def check_available(self) -> int:
        """Check if the cloud model is available via test request.

        Distinguishes between invalid API keys (warning) and other
        failures (debug) so users know when their keys are wrong.
        """
        try:
            embeddings = await self._call_provider(["test"])
            if embeddings:
                dim = len(embeddings[0])
                logger.info(f"Embedding model {self.model} available (dims={dim})")
                return dim
            return 0
        except Exception as e:
            msg = str(e).lower()
            if any(
                p in msg for p in ("401", "403", "invalid", "unauthorized", "api key")
            ):
                logger.warning(
                    f"API key invalid for {self.model}: {e}. "
                    "Check your API_KEYS configuration."
                )
            else:
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
    DEFAULT_MODEL = "n24q02m/Qwen3-Embedding-0.6B-ONNX"

    def __init__(self, model_name: str | None = None):
        self._model_name = model_name or self.DEFAULT_MODEL
        self._model = None

    def _get_model(self):
        """Lazy-load the embedding model.

        On first call, downloads the ONNX model (~570 MB) from HuggingFace
        if not already cached. Logs a warning so users know why startup is slow.
        """
        if self._model is None:
            from qwen3_embed import TextEmbedding

            logger.warning(
                f"Loading local embedding model: {self._model_name} "
                "(~570 MB download on first run). "
                "Set API_KEYS to use cloud embedding instead."
            )
            self._model = TextEmbedding(model_name=self._model_name)
            logger.info("Local embedding model loaded")
        return self._model

    async def embed_texts(
        self,
        texts: list[str],
        dimensions: int | None = None,
    ) -> list[list[float]]:
        """Embed texts using local ONNX model."""
        if not texts:
            return []

        model = self._get_model()

        # Local inference is CPU-bound, use to_thread to keep loop responsive
        def _embed():
            # Pass dim to model.embed() so MRL truncation happens BEFORE L2-normalization
            kwargs = {}
            if dimensions and dimensions > 0:
                kwargs["dim"] = dimensions
            return list(model.embed(texts, **kwargs))

        embeddings = await asyncio.to_thread(_embed)
        return [emb.tolist() for emb in embeddings]

    async def embed_single(
        self,
        text: str,
        dimensions: int | None = None,
    ) -> list[float]:
        """Embed a single text (document/passage)."""
        results = await self.embed_texts([text], dimensions)
        return results[0]

    async def embed_single_query(
        self,
        text: str,
        dimensions: int | None = None,
    ) -> list[float]:
        """Embed a query with instruction prefix (asymmetric retrieval)."""
        model = self._get_model()

        def _embed_query():
            kwargs = {}
            if dimensions and dimensions > 0:
                kwargs["dim"] = dimensions
            return list(model.query_embed(text, **kwargs))

        result = await asyncio.to_thread(_embed_query)
        return result[0].tolist()

    async def check_available(self) -> int:
        """Check if qwen3-embed is available."""
        try:
            model = self._get_model()

            def _check():
                return list(model.embed(["test"]))

            result = await asyncio.to_thread(_check)
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


def init_backend(
    backend_type: str,
    model: str | None = None,
    api_base: str | None = None,
    api_key: str | None = None,
) -> EmbeddingBackend:
    """Initialize and cache the embedding backend.

    Args:
        backend_type: 'cloud' or 'local'
        model: Model name (required for cloud, optional for local)
        api_base: Custom API base URL (cloud only)
        api_key: Custom API key (cloud only)

    Returns:
        Initialized backend instance.
    """
    global _backend

    if backend_type == "cloud":
        if not model:
            raise ValueError("model is required for cloud backend")
        _backend = CloudEmbeddingBackend(model, api_base=api_base, api_key=api_key)
    elif backend_type == "local":
        _backend = Qwen3EmbedBackend(model)
    else:
        raise ValueError(f"Unknown backend type: {backend_type}")

    return _backend
