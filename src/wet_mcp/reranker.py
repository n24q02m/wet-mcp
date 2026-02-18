"""Dual-backend reranking: LiteLLM (cloud) + qwen3-embed (local ONNX).

Supports two backends:
- **litellm**: Cloud reranking via LiteLLM arerank() (Cohere, etc.).
  Requires API keys and RERANK_MODEL config.
- **local**: Local ONNX cross-encoder via qwen3-embed (Qwen3-Reranker-0.6B).
  No API keys needed, ~0.57GB model download on first use.

Reranker takes search results and re-scores them with a cross-encoder
for better precision. Pipeline: retrieve top-30 -> rerank -> return top-N.
"""

from __future__ import annotations

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
# LiteLLM Backend (cloud)
# ---------------------------------------------------------------------------


class LiteLLMReranker:
    """Cloud reranking via LiteLLM arerank() API."""

    def __init__(self, model: str):
        self.model = model

    def rerank(
        self,
        query: str,
        documents: list[str],
        top_n: int = 10,
    ) -> list[tuple[int, float]]:
        """Rerank using LiteLLM cloud reranking API."""
        if not documents:
            return []

        try:
            import litellm

            response = litellm.rerank(
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
            logger.warning(f"LiteLLM reranking failed: {e}")
            return []

    def check_available(self) -> bool:
        """Check if LiteLLM reranking model is available."""
        try:
            import litellm

            response = litellm.rerank(
                model=self.model,
                query="test",
                documents=["test document"],
                top_n=1,
            )
            return bool(response.results)
        except Exception as e:
            logger.debug(f"LiteLLM reranker {self.model} not available: {e}")
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

    def __init__(self, model_name: str | None = None):
        self._model_name = model_name or self.DEFAULT_MODEL
        self._model = None

    def _get_model(self):
        """Lazy-load the reranking model."""
        if self._model is None:
            from qwen3_embed import TextCrossEncoder

            logger.info(f"Loading local reranker model: {self._model_name}")
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
            # qwen3-embed rerank() takes list of (query, document) pairs
            pairs = [(query, doc) for doc in documents]
            scores = list(model.rerank(pairs))

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
            scores = list(model.rerank([("test", "test document")]))
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


def init_reranker(backend_type: str, model: str | None = None) -> RerankerBackend:
    """Initialize and cache the reranker backend.

    Args:
        backend_type: 'litellm' or 'local'
        model: Model name (required for litellm, optional for local)

    Returns:
        Initialized reranker backend instance.
    """
    global _backend

    if backend_type == "litellm":
        if not model:
            raise ValueError("model is required for litellm reranker")
        _backend = LiteLLMReranker(model)
    elif backend_type == "local":
        _backend = Qwen3Reranker(model)
    else:
        raise ValueError(f"Unknown reranker backend type: {backend_type}")

    return _backend
