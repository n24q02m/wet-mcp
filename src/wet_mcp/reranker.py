"""Dual-backend reranking: Cloud (litellm passthrough) + qwen3-embed (local ONNX).

Supports two backends:
- **cloud**: Cloud reranking via mcp_core.llm (litellm passthrough — Jina,
  Cohere, or any litellm rerank 'provider/model'). Requires the matching
  provider API key env var (JINA_AI_API_KEY, COHERE_API_KEY / CO_API_KEY).
- **local**: Local ONNX cross-encoder via qwen3-embed (Qwen3-Reranker-0.6B).
  No API keys needed, ~0.57GB model download on first use.

Reranker takes search results and re-scores them with a cross-encoder
for better precision. Pipeline: retrieve top-30 -> rerank -> return top-N.
"""

from __future__ import annotations

from typing import Any, Protocol

from loguru import logger

# ---------------------------------------------------------------------------
# Backend Protocol
# ---------------------------------------------------------------------------
_AUTH_ERROR_PATTERNS = ("401", "403", "invalid", "unauthorized", "api key")


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
# Cloud Backend (litellm passthrough via mcp_core.llm)
# ---------------------------------------------------------------------------


class CloudReranker:
    """Cloud reranking via mcp_core.llm (litellm passthrough)."""

    DEFAULT_MODEL = "rerank-v4.0-pro"

    def __init__(self, model: str | None = None, api_key: str | None = None):
        self.model = model or self.DEFAULT_MODEL
        # Explicit key only. When None, litellm falls back to the provider
        # env var (JINA_AI_API_KEY, COHERE_API_KEY / CO_API_KEY) at call time.
        self.api_key = api_key or None

    def _litellm_model(self) -> str:
        """Map wet's model naming to a litellm ``provider/model`` string."""
        if "/" in self.model:
            return self.model
        if self.model.lower().startswith("jina"):
            return f"jina_ai/{self.model}"
        return f"cohere/{self.model}"

    def _call_rerank(
        self, query: str, documents: list[str], top_n: int
    ) -> list[tuple[int, float]]:
        """Single cloud path via mcp_core.llm (sync mirror — runs in to_thread)."""
        # Lazy import: litellm costs ~1-2s on first import.
        from mcp_core.llm import rerank as core_rerank

        from wet_mcp.credential_state import api_base_for_task, api_key_for_model

        litellm_model = self._litellm_model()
        # Resolve the provider key AND custom endpoint from the request-scoped
        # per-sub bucket (HTTP multi-user) or the process env (single-user);
        # explicit api_key wins. Avoids os.environ cross-user bleed. SSRF-vetted
        # downstream in mcp_core.llm dispatch.
        response = core_rerank(
            model=litellm_model,
            query=query,
            documents=documents,
            top_n=top_n,
            api_base=api_base_for_task("RERANK_API_BASE"),
            api_key=self.api_key or api_key_for_model(litellm_model),
        )

        # litellm RerankResponse.results defaults to None and rerank items
        # may be pydantic objects or plain dicts — guard + handle both shapes.
        def _idx(r: Any) -> int:
            return r["index"] if isinstance(r, dict) else getattr(r, "index", 0)

        def _score(r: Any) -> float:
            return (
                r["relevance_score"]
                if isinstance(r, dict)
                else getattr(r, "relevance_score", 0.0)
            )

        return [(_idx(r), _score(r)) for r in (response.results or [])]

    def rerank(
        self,
        query: str,
        documents: list[str],
        top_n: int = 10,
    ) -> list[tuple[int, float]]:
        """Rerank using the cloud rerank API."""
        if not documents:
            return []

        try:
            results = self._call_rerank(query, documents, top_n)

            # Sort by score descending
            results.sort(key=lambda x: x[1], reverse=True)
            return results[:top_n]

        except Exception as e:
            logger.warning(f"Cloud reranking failed: {e}")
            return []

    def check_available(self) -> bool:
        """Check if the cloud reranking model is available.

        Distinguishes between invalid API keys (warning) and other
        failures (debug) so users know when their keys are wrong.
        """
        try:
            results = self._call_rerank("test", ["test document"], 1)
            return bool(results)
        except Exception as e:
            msg = str(e).lower()
            if any(p in msg for p in _AUTH_ERROR_PATTERNS):
                logger.warning(
                    f"API key invalid for reranker {self.model}: {e}. "
                    "Check your JINA_AI_API_KEY or COHERE_API_KEY configuration."
                )
            else:
                logger.debug(f"Cloud reranker {self.model} not available: {e}")
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

    # YesNo variant: ~598 MB at inference vs ~12 GB for the full-vocab build,
    # mathematically equivalent, batch-invariant since qwen3-embed 1.11.2b3 (#725).
    DEFAULT_MODEL = "n24q02m/Qwen3-Reranker-0.6B-ONNX-YesNo"

    def __init__(self, model_name: str | None = None):
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

# Shared local ONNX reranker for the HTTP multi-user path. Local inference is
# stateless and key-free, so one instance is safely shared across subs. Lazy
# so single-user / stdio deployments never download the model unnecessarily.
_shared_local_backend: Qwen3Reranker | None = None


def get_reranker() -> RerankerBackend | None:
    """Get the current reranker backend singleton (startup-resolved)."""
    return _backend


def clear_reranker() -> None:
    """Clear the startup singleton after backend validation fails."""
    global _backend
    _backend = None


def _shared_local_reranker() -> Qwen3Reranker:
    """Return the process-shared local ONNX reranker backend (lazy)."""
    global _shared_local_backend
    if _shared_local_backend is None:
        _shared_local_backend = Qwen3Reranker()
    return _shared_local_backend


def resolve_rerank_backend_for_request() -> RerankerBackend | None:
    """Resolve the reranker backend for the CURRENT request.

    * **Stdio / single-user HTTP** (``_current_sub`` is ``None``): return the
      module-level startup singleton (:func:`get_reranker`). Unchanged.

    * **HTTP multi-user** (``_current_sub`` set): resolve PER REQUEST from the
      sub's credential bucket. If the sub has a cloud rerank chain whose
      provider key is present, build a fresh request-scoped
      :class:`CloudReranker` carrying that sub's key explicitly. With no such
      chain, fall back to the process-shared local ONNX reranker -- unless that
      leg is unavailable, in which case reranking is ``None``: gracefully
      unavailable.

    The unavailable exit mirrors :meth:`Settings.resolve_rerank_backend`, which
    spells it ``'unavailable'`` at startup, via the shared
    :meth:`Settings.local_rerank_available` predicate -- so it covers both
    ``DISABLE_LOCAL_RERANK`` and an image the slim build stripped
    ``qwen3-embed`` out of. It matters more here than the traceback suggests:
    :meth:`Qwen3Reranker.rerank` swallows its own load failure and returns
    ``[]``, so a local reranker on an image built without the ONNX extras
    degrades every search to unranked order behind one log line, quietly,
    forever. Returning ``None`` says the same thing out loud.

    ``None``, not the startup singleton -- that one carries the OPERATOR's key
    and must not be spent on an arbitrary sub.

    A per-sub request NEVER rebinds the module-level ``_backend`` singleton, so
    one user's cloud reranker/key can't serve another concurrent user.
    """
    from wet_mcp.config import settings
    from wet_mcp.credential_state import (
        api_key_for_model,
        credentials_for_current_request,
        get_current_sub,
    )

    if get_current_sub() is None:
        return get_reranker()

    if not settings.rerank_enabled:
        return None

    creds = credentials_for_current_request()
    chain = settings.rerank_chain_for_creds(creds)
    if chain:
        model = chain[0]
        return CloudReranker(model=model, api_key=api_key_for_model(model))
    if not settings.local_rerank_available():
        return None
    return _shared_local_reranker()


def init_reranker(
    backend_type: str,
    model: str | None = None,
    api_key: str | None = None,
    **kwargs,
) -> RerankerBackend:
    """Initialize and cache the reranker backend.

    Args:
        backend_type: 'cloud' or 'local'
        model: Model name (optional for cloud, defaults to rerank-v4.0-pro)
        api_key: Custom API key (cloud only)
        **kwargs: Additional keyword arguments (ignored, for backward compatibility)

    Returns:
        Initialized reranker backend instance.
    """
    global _backend

    if backend_type == "cloud":
        _backend = CloudReranker(model=model, api_key=api_key)
    elif backend_type == "local":
        _backend = Qwen3Reranker(model)
    else:
        raise ValueError(f"Unknown reranker backend type: {backend_type}")

    return _backend
