"""LLM utilities for WET MCP Server using LiteLLM"""

import base64
import logging
import mimetypes
import os
from pathlib import Path

# Silence LiteLLM completely - must be done BEFORE import
os.environ["LITELLM_LOG"] = "ERROR"

import litellm

litellm.suppress_debug_info = True  # type: ignore[assignment]
litellm.set_verbose = False

# Force redirect LiteLLM's logger to null
logging.getLogger("LiteLLM").setLevel(logging.ERROR)
logging.getLogger("LiteLLM").handlers = [logging.NullHandler()]

import asyncio  # noqa: E402

from litellm import acompletion  # noqa: E402
from loguru import logger  # noqa: E402

from wet_mcp.config import settings  # noqa: E402
from wet_mcp.security import is_safe_path  # noqa: E402


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
    """Check model's media capabilities using LiteLLM.

    Returns:
        Dict with 'vision', 'audio_input', 'audio_output' booleans.
    """
    return {
        "vision": litellm.supports_vision(model),
        "audio_input": litellm.supports_audio_input(model),
        "audio_output": litellm.supports_audio_output(model),
    }


def encode_image(image_path: str) -> str:
    """Encode image to base64."""
    with open(image_path, "rb") as image_file:
        return base64.b64encode(image_file.read()).decode("utf-8")


async def analyze_media(
    media_path: str, prompt: str = "Describe this media in detail."
) -> str:
    """Analyze media file using configured LLM with auto-capability detection."""
    if not settings.api_keys:
        return "Error: LLM analysis requires API_KEYS to be configured."

    # Security check: Ensure path is within allowed directories
    if not is_safe_path(media_path, [settings.download_dir]):
        return f"Error: Access denied. Path '{media_path}' is not within allowed directories."

    path_obj = Path(media_path)
    if not path_obj.exists():
        return f"Error: File not found at {media_path}"

    # Determine mime type
    mime_type, _ = mimetypes.guess_type(media_path)
    if not mime_type:
        return f"Error: Cannot determine file type for {media_path}"

    # Handle text files directly
    if mime_type.startswith("text/") or mime_type in [
        "application/json",
        "application/javascript",
        "application/xml",
    ]:

        def _read_and_truncate(path: str) -> str:
            """Read file and truncate if too long."""
            with open(path, encoding="utf-8") as f:
                text = f.read()
            if len(text) > 100000:
                text = text[:100000] + "\n...[truncated]"
            return text

        try:
            content = await asyncio.to_thread(_read_and_truncate, media_path)

            config = get_llm_config()
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
    config = get_llm_config()
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
        config = get_llm_config()
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
        )

        return str(response.choices[0].message.content)

    except Exception as e:
        logger.error(f"LLM analysis failed: {e}")
        return f"Error analyzing media: {str(e)}"
