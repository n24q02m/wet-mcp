"""Embedding provider using LiteLLM.

Supports any provider that LiteLLM handles:
- OpenAI, Gemini, Mistral, Cohere (cloud, API key required)
- Any OpenAI-compatible endpoint

Auto-detects provider from API_KEYS config.
Embeddings are truncated to fixed dims in server._embed().
"""

import logging
import os
import time

# Silence LiteLLM before import
os.environ.setdefault("LITELLM_LOG", "ERROR")

import litellm

litellm.suppress_debug_info = True  # type: ignore[assignment]
litellm.set_verbose = False
logging.getLogger("LiteLLM").setLevel(logging.ERROR)
logging.getLogger("LiteLLM").handlers = [logging.NullHandler()]

from litellm import embedding as litellm_embedding  # noqa: E402
from loguru import logger  # noqa: E402

# Gemini API: max 100 texts per batch request.
# Other providers (OpenAI, Cohere) allow more but 100 is safe for all.
MAX_BATCH_SIZE = 100

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


def _embed_batch(
    texts: list[str],
    model: str,
    dimensions: int | None = None,
) -> list[list[float]]:
    """Embed a single batch with retry logic for transient errors."""
    kwargs: dict = {
        "model": model,
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
                    f"Embedding retry {attempt + 1}/{MAX_RETRIES} after {delay}s: {e}"
                )
                time.sleep(delay)
            else:
                break

    logger.error(f"Embedding failed ({model}): {last_exc}")
    raise last_exc  # type: ignore[misc]


def embed_texts(
    texts: list[str],
    model: str,
    dimensions: int | None = None,
) -> list[list[float]]:
    """Embed texts using LiteLLM (supports all providers).

    Automatically splits large inputs into batches of MAX_BATCH_SIZE
    to respect API limits (e.g., Gemini max 100 per request).
    Retries transient errors with exponential backoff.

    Args:
        texts: List of texts to embed.
        model: LiteLLM model string (e.g., "gemini/text-embedding-004").
        dimensions: Optional output dimensions (for models that support it).

    Returns:
        List of embedding vectors.
    """
    if not texts:
        return []

    # Single batch -- no splitting needed
    if len(texts) <= MAX_BATCH_SIZE:
        return _embed_batch(texts, model, dimensions)

    # Split into batches
    all_embeddings: list[list[float]] = []
    total_batches = (len(texts) + MAX_BATCH_SIZE - 1) // MAX_BATCH_SIZE
    logger.info(
        f"Splitting {len(texts)} texts into {total_batches} batches "
        f"(max {MAX_BATCH_SIZE}/batch)"
    )

    for i in range(0, len(texts), MAX_BATCH_SIZE):
        batch = texts[i : i + MAX_BATCH_SIZE]
        batch_num = i // MAX_BATCH_SIZE + 1
        logger.debug(f"Embedding batch {batch_num}/{total_batches}: {len(batch)} texts")
        batch_result = _embed_batch(batch, model, dimensions)
        all_embeddings.extend(batch_result)

    return all_embeddings


def embed_single(
    text: str,
    model: str,
    dimensions: int | None = None,
) -> list[float]:
    """Embed a single text."""
    results = embed_texts([text], model, dimensions)
    return results[0]


def check_embedding_available(model: str) -> int:
    """Check if an embedding model is available.

    Sends a test request to verify the model works.

    Returns:
        Embedding dimensions if available, 0 if not.
    """
    try:
        response = litellm_embedding(model=model, input=["test"])
        if response.data:
            dim = len(response.data[0]["embedding"])
            logger.info(f"Embedding model {model} available (dims={dim})")
            return dim
        return 0
    except Exception as e:
        logger.debug(f"Embedding model {model} not available: {e}")
        return 0
