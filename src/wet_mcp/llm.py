"""LLM utilities for WET MCP Server using LiteLLM."""

import base64
import mimetypes
from pathlib import Path

from litellm import completion
from loguru import logger

from wet_mcp.config import settings


def get_llm_config() -> dict:
    """Build LLM configuration with fallback."""
    models = [m.strip() for m in settings.llm_models.split(",") if m.strip()]
    if not models:
        models = ["gemini/gemini-3-flash-preview"]

    primary = models[0]
    fallbacks = models[1:] if len(models) > 1 else None

    # Temperature adjustment for reasoning models
    # (Gemini 2/3 sometimes needs higher temp, but 1.5 is standard)
    temperature = 0.1

    return {
        "model": primary,
        "fallbacks": fallbacks,
        "temperature": temperature,
    }


def encode_image(image_path: str) -> str:
    """Encode image to base64."""
    with open(image_path, "rb") as image_file:
        return base64.b64encode(image_file.read()).decode("utf-8")


async def analyze_media(
    media_path: str, prompt: str = "Describe this image in detail."
) -> str:
    """Analyze media file using configured LLM."""
    if not settings.api_keys:
        return "Error: LLM analysis requires API_KEYS to be configured."

    path_obj = Path(media_path)
    if not path_obj.exists():
        return f"Error: File not found at {media_path}"

    # Determine mime type
    mime_type, _ = mimetypes.guess_type(media_path)
    if not mime_type or not mime_type.startswith("image/"):
        return f"Error: Only image analysis is currently supported. Got {mime_type}"

    try:
        config = get_llm_config()
        logger.info(f"Analyzing media with model: {config['model']}")

        base64_image = encode_image(media_path)
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

        response = completion(
            model=config["model"],
            messages=messages,
            fallbacks=config["fallbacks"],
            temperature=config["temperature"],
        )

        content = response.choices[0].message.content
        return content

    except Exception as e:
        logger.error(f"LLM analysis failed: {e}")
        return f"Error analyzing media: {str(e)}"
