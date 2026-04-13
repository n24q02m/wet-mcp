"""Setup tool -- warmup and setup-sync logic as MCP-callable functions.

Extracted from __main__.py CLI commands into async functions that return
structured dicts for MCP tool responses.
"""

import asyncio
import os
import shutil
import tempfile
from pathlib import Path

from loguru import logger

from wet_mcp.config import _EMBEDDING_CANDIDATES, settings


def clear_model_cache(model_name: str) -> str | None:
    """Remove corrupted HuggingFace cache for a model so it re-downloads.

    Returns the path that was cleared, or None if no cache existed.
    """
    cache_dir = Path(
        os.getenv(
            "QWEN3_EMBED_CACHE_PATH",
            os.path.join(tempfile.gettempdir(), "qwen3_embed_cache"),
        )
    )
    safe_name = model_name.replace("/", "--")
    model_cache = cache_dir / f"models--{safe_name}"
    if model_cache.exists():
        shutil.rmtree(model_cache)
        return str(model_cache)
    return None


async def _validate_cloud_models(settings_obj) -> dict:
    """Check if cloud embedding and reranking models are valid."""
    from wet_mcp.embedder import init_backend
    from wet_mcp.reranker import init_reranker

    model = settings_obj.resolve_embedding_model()
    candidates = [model] if model else _EMBEDDING_CANDIDATES

    embedding_info = None
    for candidate in candidates:
        try:
            backend = init_backend("cloud", candidate)
            dims = await backend.check_available()
            if dims > 0:
                embedding_info = {"model": candidate, "dims": dims}
                break
        except Exception as exc:
            logger.debug(f"Cloud embedding candidate {candidate} failed: {exc}")
            continue

    if not embedding_info:
        return {"cloud_ready": False}

    reranker_info = None
    rerank_model = settings_obj.resolve_rerank_model()
    if rerank_model:
        try:
            reranker = init_reranker("cloud", rerank_model)
            if reranker.check_available():
                reranker_info = {"model": rerank_model}
        except Exception as exc:
            logger.debug(f"Cloud reranker {rerank_model} failed: {exc}")
            pass

    return {
        "cloud_ready": True,
        "embedding": embedding_info,
        "reranker": reranker_info,
    }


def _download_local_embedding(settings_obj) -> dict:
    """Download and validate local embedding model."""
    from qwen3_embed import TextEmbedding

    local_model = settings_obj.resolve_local_embedding_model()
    try:
        embed_model = TextEmbedding(model_name=local_model)
        result = list(embed_model.embed(["warmup test"]))
        if result:
            return {
                "step": "local_embedding",
                "status": "ok",
                "model": local_model,
                "dims": len(result[0]),
            }
        return {
            "step": "local_embedding",
            "status": "warning",
            "message": "Embedding test returned empty result",
        }
    except Exception as exc:
        if "NO_SUCHFILE" in str(exc) or "doesn't exist" in str(exc):
            cleared = clear_model_cache(local_model)
            logger.info(f"Cleared corrupted cache: {cleared}")
            embed_model = TextEmbedding(model_name=local_model)
            result = list(embed_model.embed(["warmup test"]))
            if result:
                return {
                    "step": "local_embedding",
                    "status": "ok",
                    "model": local_model,
                    "dims": len(result[0]),
                    "retried": True,
                }
            return {
                "step": "local_embedding",
                "status": "warning",
                "message": "Embedding test failed after cache clear",
            }
        raise


def _download_local_reranker(settings_obj) -> dict:
    """Download and validate local reranker model."""
    if not settings_obj.rerank_enabled:
        return {
            "step": "local_reranker",
            "status": "skipped",
            "message": "Reranking disabled",
        }

    from qwen3_embed import TextCrossEncoder

    local_model = settings_obj.resolve_local_rerank_model()
    try:
        reranker = TextCrossEncoder(model_name=local_model)
        scores = list(reranker.rerank("test query", ["test document"]))
        if scores:
            return {
                "step": "local_reranker",
                "status": "ok",
                "model": local_model,
            }
        return {
            "step": "local_reranker",
            "status": "warning",
            "message": "Reranker test returned empty result",
        }
    except Exception as exc:
        if "NO_SUCHFILE" in str(exc) or "doesn't exist" in str(exc):
            cleared = clear_model_cache(local_model)
            logger.info(f"Cleared corrupted cache: {cleared}")
            reranker = TextCrossEncoder(model_name=local_model)
            scores = list(reranker.rerank("test query", ["test document"]))
            if scores:
                return {
                    "step": "local_reranker",
                    "status": "ok",
                    "model": local_model,
                    "retried": True,
                }
            return {
                "step": "local_reranker",
                "status": "warning",
                "message": "Reranker test failed after cache clear",
            }
        raise


async def run_warmup() -> dict:
    """Pre-download models and run setup to avoid first-run delays.

    Returns a structured dict with warmup results:
    {
        "status": "ok" | "error",
        "mode": "cloud" | "local",
        "steps": [{"step": str, "status": str, ...}, ...],
        "embedding": {...},  # if cloud
        "reranker": {...},   # if cloud reranker available
    }
    """
    steps = []

    # 1. Run auto-setup (SearXNG + Playwright)
    try:
        from wet_mcp.setup import run_auto_setup

        await asyncio.to_thread(run_auto_setup)
        steps.append({"step": "auto_setup", "status": "ok"})
    except Exception as exc:
        steps.append(
            {
                "step": "auto_setup",
                "status": "warning",
                "error": str(exc),
            }
        )

    # 2. Check cloud models if API keys are configured
    mode = settings.setup_providers()
    if mode == "sdk":
        cloud_result = await _validate_cloud_models(settings)
        if cloud_result["cloud_ready"]:
            steps.append(
                {
                    "step": "cloud_models",
                    "status": "ok",
                    "provider_mode": mode,
                }
            )
            return {
                "status": "ok",
                "mode": "cloud",
                "steps": steps,
                "embedding": cloud_result["embedding"],
                "reranker": cloud_result.get("reranker"),
            }
        steps.append(
            {
                "step": "cloud_models",
                "status": "fallback",
                "message": "Cloud models not available, falling back to local",
            }
        )

    # 3. Download local models
    embed_result = await asyncio.to_thread(_download_local_embedding, settings)
    steps.append(embed_result)

    reranker_result = await asyncio.to_thread(_download_local_reranker, settings)
    steps.append(reranker_result)

    return {
        "status": "ok",
        "mode": "local",
        "steps": steps,
    }


async def run_setup_sync(remote_type: str = "drive") -> dict:
    """Run Google Drive sync setup (OAuth Device Code flow).

    Returns a structured dict with setup results.
    """
    try:
        from wet_mcp.sync import setup_google_auth

        success = await setup_google_auth()
        if success:
            return {
                "status": "ok",
                "provider": "google_drive",
                "message": "Google Drive sync setup complete. Token saved locally.",
            }
        return {
            "status": "error",
            "provider": "google_drive",
            "error": "Authentication failed or was cancelled",
        }
    except Exception as exc:
        return {
            "status": "error",
            "provider": "google_drive",
            "error": str(exc),
        }
