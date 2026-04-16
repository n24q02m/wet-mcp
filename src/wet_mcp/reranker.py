"""Dual-backend reranking: Cohere SDK (cloud) + qwen3-embed (local ONNX).

Supports two backends:
- **cloud**: Cloud reranking via Cohere SDK (rerank-v4.0-pro).
  Requires COHERE_API_KEY or CO_API_KEY env var.
- **local**: Local ONNX cross-encoder via qwen3-embed (Qwen3-Reranker-0.6B).
  No API keys needed, ~0.57GB model download on first use.

Reranker takes search results and re-scores them with a cross-encoder
for better precision. Pipeline: retrieve top-30 -> rerank -> return top-N.
"""

from __future__ import annotations

import os
from typing import Protocol

from loguru import logger

# ---------------------------------------------------------------------------
# Backend Protocol
# ---------------------------------------------------------------------------


class RerankerBackend(Protocol):
    """Protocol for reranker backends."""

    def rerank(
        self,
        query: str,
        documents: list[str],
        top_n: int = 10,
    ) -> list[tuple[int, float]]:
        """Rerank documents against a query.

        Args:
            query: Search query text.
            documents: List of document texts to rerank.
            top_n: Return top N results.

        Returns:

            List of (original_index, score) tuples, sorted by score descending.
        """
        ...

    def check_available(self) -> bool:
        """Check if the reranker backend is available."""
        ...


# ---------------------------------------------------------------------------
# Cohere Backend (cloud)
# ---------------------------------------------------------------------------


class CohereReranker:
    """Cloud reranking via Cohere SDK (ClientV2)."""

    DEFAULT_MODEL = "rerank-v4.0-pro"

    def __init__(self, model: str | None = None, api_key: str | None = None) -> None:
        self.model = model or self.DEFAULT_MODEL
        self.api_key = api_key or os.environ.get(
            "COHERE_API_KEY", os.environ.get("CO_API_KEY", "")
        )

    def _get_client(self):
        """Create a Cohere ClientV2 instance."""
        import cohere

        return cohere.ClientV2(api_key=self.api_key)

    def rerank(
        self,
        query: str,
        documents: list[str],
        top_n: int = 10,
    ) -> list[tuple[int, float]]:
        """Rerank using Cohere rerank API."""
        if not documents:
            return []

        try:
            client = self._get_client()
            response = client.rerank(
                model=self.model,
                query=query,
                documents=documents,
                top_n=top_n,
            )

            results = []
            for item in response.results:
                results.append((item.index, item.relevance_score))

            # Sort by score descending
            results.sort(key=lambda x: x[1], reverse=True)
            return results[:top_n]

        except Exception as e:
            logger.warning(f"Cohere reranking failed: {e}")
            return []

    def check_available(self) -> bool:
        """Check if Cohere reranking model is available.

        Distinguishes between invalid API keys (warning) and other
        failures (debug) so users know when their keys are wrong.
        """
        try:
            client = self._get_client()
            response = client.rerank(
                model=self.model,
                query="test",
                documents=["test document"],
                top_n=1,
            )
            return bool(response.results)
        except Exception as e:
            msg = str(e).lower()
            if any(
                p in msg for p in ("401", "403", "invalid", "unauthorized", "api key")
            ):
                logger.warning(
                    f"API key invalid for reranker {self.model}: {e}. "
                    "Check your COHERE_API_KEY or CO_API_KEY configuration."
                )
            else:
                logger.debug(f"Cohere reranker {self.model} not available: {e}")
            return False


# ---------------------------------------------------------------------------
# qwen3-embed Backend (local ONNX)
# ---------------------------------------------------------------------------


class Qwen3Reranker:
    """Local ONNX cross-encoder reranking via qwen3-embed (Qwen3-Reranker-0.6B).

    Uses causal LM yes/no logit scoring with chat template.
    Scores are P(yes) in [0, 1].
    Model is downloaded on first use (~0.57GB).
    """

    DEFAULT_MODEL = "n24q02m/Qwen3-Reranker-0.6B-ONNX"

    def __init__(self, model_name: str | None = None) -> None:
        self._model_name = model_name or self.DEFAULT_MODEL
        self._model = None

    def _get_model(self):
        """Lazy-load the reranking model.

        On first call, downloads the ONNX model (~570 MB) from HuggingFace
        if not already cached. Logs a warning so users know why startup is slow.
        """
        if self._model is None:
            from qwen3_embed import TextCrossEncoder

            logger.warning(
                f"Loading local reranker model: {self._model_name} "
                "(~570 MB download on first run). "
                "Set API_KEYS with COHERE_API_KEY to use cloud reranking instead."
            )
            self._model = TextCrossEncoder(model_name=self._model_name)
            logger.info("Local reranker model loaded")
        return self._model

    def rerank(
        self,
        query: str,
        documents: list[str],
        top_n: int = 10,
    ) -> list[tuple[int, float]]:
        """Rerank documents using local cross-encoder."""
        if not documents:
            return []

        try:
            model = self._get_model()
            scores = list(model.rerank(query, documents))

            # Build (index, score) pairs
            results = list(enumerate(scores))
            # Sort by score descending
            results.sort(key=lambda x: x[1], reverse=True)
            return results[:top_n]

        except Exception as e:
            logger.warning(f"Local reranking failed: {e}")
            return []

    def check_available(self) -> bool:
        """Check if qwen3-embed reranker is available."""
        try:
            model = self._get_model()
            scores = list(model.rerank("test", ["test document"]))
            return len(scores) > 0
        except Exception as e:
            logger.debug(f"Local reranker not available: {e}")
            return False


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

_backend: RerankerBackend | None = None


def get_reranker() -> RerankerBackend | None:
    """Get the current reranker backend singleton."""
    return _backend


def init_reranker(
    backend_type: str,
    model: str | None = None,
    api_key: str | None = None,
) -> RerankerBackend:
    """Initialize and cache the reranker backend.

    Args:
        backend_type: 'cloud' or 'local'
        model: Model name (optional for cloud, defaults to rerank-v4.0-pro)
        api_key: Custom API key (cloud only)
    Returns:

        Initialized reranker backend instance.
    """
    global _backend

    if backend_type == "cloud":
        _backend = CohereReranker(model=model, api_key=api_key)
    elif backend_type == "local":
        _backend = Qwen3Reranker(model)
    else:
        raise ValueError(f"Unknown reranker backend type: {backend_type}")

    return _backend
