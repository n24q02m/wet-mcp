"""Embedding provider using LiteLLM.

Supports any provider that LiteLLM handles:
- OpenAI, Gemini, Mistral, Cohere (cloud, API key required)
- Any OpenAI-compatible endpoint

Auto-detects provider from API_KEYS config.
Embeddings are truncated to fixed dims in server._embed().
"""

import logging
import os

# Silence LiteLLM before import
os.environ.setdefault("LITELLM_LOG", "ERROR")

import litellm

litellm.suppress_debug_info = True  # type: ignore[assignment]
litellm.set_verbose = False
logging.getLogger("LiteLLM").setLevel(logging.ERROR)
logging.getLogger("LiteLLM").handlers = [logging.NullHandler()]

from litellm import embedding as litellm_embedding  # noqa: E402
from loguru import logger  # noqa: E402


def embed_texts(
    texts: list[str],
    model: str,
    dimensions: int | None = None,
) -> list[list[float]]:
    """Embed texts using LiteLLM (supports all providers).

    Args:
        texts: List of texts to embed.
        model: LiteLLM model string (e.g., "gemini/text-embedding-004").
        dimensions: Optional output dimensions (for models that support it).

    Returns:
        List of embedding vectors.
    """
    if not texts:
        return []

    kwargs: dict = {
        "model": model,
        "input": texts,
    }
    if dimensions:
        kwargs["dimensions"] = dimensions

    try:
        response = litellm_embedding(**kwargs)
        # Sort by index to ensure correct order
        data = sorted(response.data, key=lambda x: x["index"])
        return [d["embedding"] for d in data]
    except Exception as e:
        logger.error(f"Embedding failed ({model}): {e}")
        raise


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
