"""LLM utilities for WET MCP Server using native provider SDKs."""

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
# Native async completion
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
    """Unified async completion using native SDKs.

    Routes to google-genai or openai based on model prefix.
    Returns an OpenAI-compatible response object.
    """
    provider = _detect_provider(model)
    bare_model = _strip_provider(model)

    try:
        if provider == "gemini":
            return await _gemini_completion(
                model=bare_model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                response_format=response_format,
                api_key=api_key,
            )
        else:
            # OpenAI-compatible (openai, xai/grok)
            return await _openai_completion(
                provider=provider,
                model=bare_model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                response_format=response_format,
                api_base=api_base,
                api_key=api_key,
            )
    except Exception as e:
        # Try fallbacks
        if fallbacks:
            for fb_model in fallbacks:
                try:
                    return await acompletion(
                        model=fb_model,
                        messages=messages,
                        temperature=temperature,
                        max_tokens=max_tokens,
                        response_format=response_format,
                        api_base=api_base,
                        api_key=api_key,
                    )
                except Exception:
                    continue
        raise e


class _Choice:
    """Minimal OpenAI-compatible choice object."""

    def __init__(self, content: str):
        self.message = _Message(content)


class _Message:
    """Minimal OpenAI-compatible message object."""

    def __init__(self, content: str):
        self.content = content


class _Response:
    """Minimal OpenAI-compatible response object."""

    def __init__(self, content: str):
        self.choices = [_Choice(content)]


async def _gemini_completion(
    *,
    model: str,
    messages: list[dict],
    temperature: float | None = None,
    max_tokens: int | None = None,
    response_format: dict | None = None,
    api_key: str | None = None,
) -> _Response:
    """Call Gemini via google-genai SDK."""
    from google import genai

    key = api_key or os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or ""
    client = genai.Client(api_key=key)

    # Convert OpenAI-style messages to Gemini format
    contents = _convert_messages_to_gemini(messages)

    # Build config
    config_kwargs: dict = {}
    if temperature is not None:
        config_kwargs["temperature"] = temperature
    if max_tokens is not None:
        config_kwargs["max_output_tokens"] = max_tokens

    # Handle response_format
    if response_format:
        fmt_type = response_format.get("type", "")
        if fmt_type == "json_object":
            config_kwargs["response_mime_type"] = "application/json"
        elif fmt_type == "json_schema":
            config_kwargs["response_mime_type"] = "application/json"

    config = (
        genai.types.GenerateContentConfig(**config_kwargs) if config_kwargs else None
    )

    response = await asyncio.to_thread(
        client.models.generate_content,
        model=model,
        contents=contents,
        config=config,
    )

    text = response.text or ""
    return _Response(text)


def _convert_messages_to_gemini(messages: list[dict]) -> list:
    """Convert OpenAI-style messages to Gemini contents format."""
    from google.genai import types

    contents = []
    system_text = ""

    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")

        if role == "system":
            system_text = content if isinstance(content, str) else str(content)
            continue

        gemini_role = "user" if role == "user" else "model"

        if isinstance(content, str):
            parts = [types.Part.from_text(text=content)]
        elif isinstance(content, list):
            parts = []
            for item in content:
                if isinstance(item, dict):
                    if item.get("type") == "text":
                        parts.append(types.Part.from_text(text=item.get("text", "")))
                    elif item.get("type") == "image_url":
                        url = item.get("image_url", {}).get("url", "")
                        if url.startswith("data:"):
                            # Parse data URL: data:mime;base64,data
                            header, b64_data = url.split(",", 1)
                            mime = header.split(":")[1].split(";")[0]
                            import base64 as b64mod

                            raw = b64mod.b64decode(b64_data)
                            parts.append(
                                types.Part.from_bytes(data=raw, mime_type=mime)
                            )
                        else:
                            parts.append(
                                types.Part.from_uri(
                                    file_uri=url, mime_type="image/jpeg"
                                )
                            )
                else:
                    parts.append(types.Part.from_text(text=str(item)))
        else:
            parts = [types.Part.from_text(text=str(content))]

        # Prepend system instruction to first user message
        if system_text and gemini_role == "user":
            parts.insert(0, types.Part.from_text(text=f"[System: {system_text}]\n\n"))
            system_text = ""

        contents.append(types.Content(role=gemini_role, parts=parts))

    return contents


async def _openai_completion(
    *,
    provider: str,
    model: str,
    messages: list[dict],
    temperature: float | None = None,
    max_tokens: int | None = None,
    response_format: dict | None = None,
    api_base: str | None = None,
    api_key: str | None = None,
) -> object:
    """Call OpenAI-compatible API (OpenAI, xAI/Grok)."""
    from openai import AsyncOpenAI

    if provider == "xai":
        key = api_key or os.getenv("XAI_API_KEY") or ""
        base = api_base or "https://api.x.ai/v1"
    else:
        key = api_key or os.getenv("OPENAI_API_KEY") or ""
        base = api_base or "https://api.openai.com/v1"

    client = AsyncOpenAI(api_key=key, base_url=base)

    kwargs: dict = {
        "model": model,
        "messages": messages,
    }
    if temperature is not None:
        kwargs["temperature"] = temperature
    if max_tokens is not None:
        kwargs["max_tokens"] = max_tokens
    if response_format:
        # OpenAI supports response_format directly
        kwargs["response_format"] = response_format

    return await client.chat.completions.create(**kwargs)


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
    """Check model's media capabilities using hardcoded maps.

    Returns:
        Dict with 'vision', 'audio_input', 'audio_output' booleans.
    """
    bare = _strip_provider(model)
    return {
        "vision": bare in _VISION_MODELS,
        "audio_input": bare in _AUDIO_INPUT_MODELS,
        "audio_output": bare in _AUDIO_OUTPUT_MODELS,
    }


def encode_image(image_path: str) -> str:
    """Encode image to base64."""
    with open(image_path, "rb") as image_file:
        return base64.b64encode(image_file.read()).decode("utf-8")


def _read_and_truncate(path: str) -> str:
    """Read file and truncate if too long."""
    with open(path, encoding="utf-8") as f:
        text = f.read()
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
            content = await asyncio.to_thread(_read_and_truncate, media_path)
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

        base64_image = await asyncio.to_thread(encode_image, media_path)
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
