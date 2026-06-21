"""LLM utilities for WET MCP Server — litellm passthrough via mcp_core.llm."""

import asyncio
import base64
import mimetypes
import os
from pathlib import Path

from loguru import logger

from wet_mcp.config import settings

# ---------------------------------------------------------------------------
# Capability maps (vision / audio support detection)
# ---------------------------------------------------------------------------

_VISION_MODELS = {
    "gemini-3.1-pro-preview",
    "gemini-3-flash-preview",
    "gemini-2.5-flash",
    "gemini-2.5-pro",
    "grok-4-1-fast-reasoning",
    "grok-4-1-fast-non-reasoning",
}

_AUDIO_INPUT_MODELS = {
    "gemini-3.1-pro-preview",
    "gemini-3-flash-preview",
    "gemini-2.5-flash",
    "gemini-2.5-pro",
}

_AUDIO_OUTPUT_MODELS: set[str] = set()


def _strip_provider(model: str) -> str:
    """Strip provider prefix (e.g. 'gemini/gemini-3-flash-preview' -> 'gemini-3-flash-preview')."""
    if "/" in model:
        return model.split("/", 1)[1]
    return model


# ---------------------------------------------------------------------------
# Provider detection
# ---------------------------------------------------------------------------


def _has_llm_provider() -> bool:
    """Check if any LLM provider API key is configured."""
    return bool(
        os.getenv("GEMINI_API_KEY")
        or os.getenv("GOOGLE_API_KEY")
        or os.getenv("OPENAI_API_KEY")
        or os.getenv("XAI_API_KEY")
    )


def _detect_provider(model: str) -> str:
    """Detect provider from model string prefix.

    Returns 'gemini', 'openai', or 'xai'.
    Falls back to 'gemini' if no prefix.
    """
    if "/" in model:
        prefix = model.split("/", 1)[0].lower()
        if prefix in ("gemini", "google"):
            return "gemini"
        if prefix in ("openai", "gpt"):
            return "openai"
        if prefix in ("xai", "grok"):
            return "xai"
    # Default: check available keys
    if os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY"):
        return "gemini"
    if os.getenv("XAI_API_KEY"):
        return "xai"
    if os.getenv("OPENAI_API_KEY"):
        return "openai"
    return "gemini"


# ---------------------------------------------------------------------------
# Async completion (litellm passthrough via mcp_core.llm)
# ---------------------------------------------------------------------------


async def acompletion(
    *,
    model: str,
    messages: list[dict],
    temperature: float | None = None,
    max_tokens: int | None = None,
    response_format: dict | None = None,
    fallbacks: list[str] | None = None,
    api_base: str | None = None,
    api_key: str | None = None,
    **kwargs,
) -> object:
    """Unified async completion via mcp_core.llm (litellm passthrough).

    litellm infers the provider from the ``provider/model`` prefix and
    returns OpenAI-shaped responses (``resp.choices[0].message.content``).
    Fallback policy stays wet-owned: fallbacks are tried sequentially,
    their exceptions are swallowed, and the primary exception is re-raised
    when all fail.
    """
    # Lazy import: litellm costs ~1-2s on first import.
    from mcp_core.llm import acompletion as core_acompletion

    call_kwargs: dict = dict(kwargs)
    if temperature is not None:
        call_kwargs["temperature"] = temperature
    if max_tokens is not None:
        call_kwargs["max_tokens"] = max_tokens
    if response_format is not None:
        call_kwargs["response_format"] = response_format

    from wet_mcp.credential_state import api_key_for_model

    resolved_api_base = api_base or os.getenv("LLM_API_BASE") or None
    # Resolve the provider key from the request-scoped per-sub bucket (HTTP
    # multi-user) or the process env (single-user); an explicit api_key wins.
    # Resolved per model so a fallback to a different provider gets its own
    # key. Avoids relying on os.environ (cross-user bleed). Empty string ->
    # None so litellm's own provider env fallback still applies single-user.
    resolved_api_key = api_key or api_key_for_model(model) or None

    try:
        return await core_acompletion(
            model=model,
            messages=messages,
            api_base=resolved_api_base,
            api_key=resolved_api_key,
            **call_kwargs,
        )
    except Exception as e:
        # Try fallbacks
        if fallbacks:
            for fb_model in fallbacks:
                try:
                    return await core_acompletion(
                        model=fb_model,
                        messages=messages,
                        api_base=resolved_api_base,
                        api_key=api_key or api_key_for_model(fb_model) or None,
                        **call_kwargs,
                    )
                except Exception:
                    continue
        raise e


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get_llm_config() -> dict:
    """Build LLM configuration with fallback."""
    models = [m.strip() for m in settings.llm_models.split(",") if m.strip()]
    if not models:
        models = ["gemini/gemini-3-flash-preview"]

    primary = models[0]
    fallbacks = models[1:] if len(models) > 1 else None

    return {
        "model": primary,
        "fallbacks": fallbacks,
        "temperature": settings.llm_temperature,
    }


def get_model_capabilities(model: str) -> dict:
    """Check model's media capabilities.

    Vision comes from the litellm registry (``mcp_core.llm.supports_vision``);
    models unknown to the registry fall back to the hardcoded map. Audio
    flags stay hardcoded-map-based (no registry coverage).

    Returns:
        Dict with 'vision', 'audio_input', 'audio_output' booleans.
    """
    from mcp_core.llm import supports_vision

    bare = _strip_provider(model)
    vision = supports_vision(model)
    if vision is None:
        vision = bare in _VISION_MODELS
    return {
        "vision": vision,
        "audio_input": bare in _AUDIO_INPUT_MODELS,
        "audio_output": bare in _AUDIO_OUTPUT_MODELS,
    }


async def encode_image(image_path: str) -> str:
    """Encode image to base64.

    Offload blocking I/O to thread pool to prevent event loop lag.
    """
    data = await asyncio.to_thread(Path(image_path).read_bytes)
    return base64.b64encode(data).decode("utf-8")


async def _read_and_truncate(path: str) -> str:
    """Read file and truncate if too long.

    Uses asyncio.to_thread for non-blocking file I/O.
    """

    def _read():
        with open(path, encoding="utf-8") as f:
            return f.read(100001)

    text = await asyncio.to_thread(_read)
    if len(text) > 100000:
        text = text[:100000] + "\n...[truncated]"
    return text


async def analyze_media(
    media_path: str, prompt: str = "Describe this media in detail."
) -> str:
    """Analyze media file using configured LLM with auto-capability detection."""
    if not _has_llm_provider():
        return "Error: LLM analysis requires API keys (GEMINI_API_KEY, OPENAI_API_KEY, or XAI_API_KEY) to be configured."

    path_obj = Path(media_path).resolve()
    download_dir = Path(settings.download_dir).expanduser().resolve()
    if not path_obj.is_relative_to(download_dir):
        return f"Error: Access denied — file must be within download directory ({download_dir})"
    if not path_obj.exists():
        return f"Error: File not found at {media_path}"

    # Determine mime type
    mime_type, _ = mimetypes.guess_type(media_path)
    if not mime_type:
        return f"Error: Cannot determine file type for {media_path}"
    config = get_llm_config()

    # Handle text files directly
    if mime_type.startswith("text/") or mime_type in [
        "application/json",
        "application/javascript",
        "application/xml",
    ]:
        try:
            content = await _read_and_truncate(media_path)
            logger.info(f"Analyzing text file with model: {config['model']}")

            messages = [
                {
                    "role": "user",
                    "content": f"{prompt}\n\nFile Content:\n```\n{content}\n```",
                }
            ]
            response = await acompletion(
                model=config["model"],
                messages=messages,
                fallbacks=config["fallbacks"],
                temperature=config["temperature"],
            )
            return str(response.choices[0].message.content)
        except Exception as e:
            return f"Error analyzing text file: {e}"

    # Check model capabilities for media
    caps = get_model_capabilities(config["model"])

    # Validate capability vs file type
    if mime_type.startswith("image/"):
        if not caps["vision"]:
            return f"Error: Model {config['model']} does not support vision/images."
    elif mime_type.startswith("audio/"):
        if not caps["audio_input"]:
            return f"Error: Model {config['model']} does not support audio input."
    elif mime_type.startswith("video/"):
        if not caps["vision"]:
            return f"Error: Model {config['model']} does not support video (requires vision)."
    else:
        return f"Error: Unsupported media type: {mime_type}"

    try:
        logger.info(f"Analyzing media with model: {config['model']}")

        base64_image = await encode_image(media_path)
        data_url = f"data:{mime_type};base64,{base64_image}"

        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": data_url}},
                ],
            }
        ]

        response = await acompletion(
            model=config["model"],
            messages=messages,
            fallbacks=config["fallbacks"],
            temperature=config["temperature"],
            api_base=config.get("api_base"),
            api_key=config.get("api_key"),
        )

        return str(response.choices[0].message.content)

    except Exception as e:
        logger.error(f"LLM analysis failed: {e}")
        return f"Error analyzing media: {str(e)}"
