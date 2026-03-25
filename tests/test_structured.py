"""Tests for LLM-powered structured data extraction."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

from wet_mcp.sources.structured import extract_structured

SAMPLE_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "price": {"type": "number"},
    },
    "required": ["title", "price"],
}

SAMPLE_PAGES = [
    {
        "url": "https://example.com/product",
        "title": "Example Product",
        "content": "# Product\nTitle: Widget\nPrice: $29.99",
    }
]


def _mock_llm_response(content: str) -> MagicMock:
    """Build a mock LLM response object."""
    msg = MagicMock()
    msg.content = content
    choice = MagicMock()
    choice.message = msg
    resp = MagicMock()
    resp.choices = [choice]
    return resp


async def test_extract_structured_success():
    """LLM returns valid JSON matching schema -- happy path."""
    llm_output = json.dumps({"title": "Widget", "price": 29.99})

    with (
        patch(
            "wet_mcp.sources.structured.raw_extract",
            new_callable=AsyncMock,
            return_value=json.dumps(SAMPLE_PAGES),
        ),
        patch(
            "wet_mcp.sources.structured.settings",
        ) as mock_settings,
        patch(
            "wet_mcp.sources.structured.get_llm_config",
            return_value={"model": "gpt-4", "fallbacks": None, "temperature": 0},
        ),
        patch(
            "wet_mcp.sources.structured.acompletion",
            new_callable=AsyncMock,
            return_value=_mock_llm_response(llm_output),
        ),
    ):
        mock_settings.resolve_provider_mode.return_value = "proxy"

        result_str = await extract_structured(
            urls=["https://example.com/product"],
            schema=SAMPLE_SCHEMA,
        )

        result = json.loads(result_str)
        assert "data" in result
        assert result["data"]["title"] == "Widget"
        assert result["data"]["price"] == 29.99
        assert result["urls"] == ["https://example.com/product"]
        assert "validation_warning" not in result


async def test_extract_structured_local_mode_error():
    """Local mode (no LLM) returns an error."""
    with patch("wet_mcp.sources.structured.settings") as mock_settings:
        mock_settings.resolve_provider_mode.return_value = "local"

        result_str = await extract_structured(
            urls=["https://example.com"],
            schema=SAMPLE_SCHEMA,
        )

        result = json.loads(result_str)
        assert "error" in result
        assert "LLM" in result["error"]


async def test_extract_structured_no_content():
    """Empty/error pages return an error about no content."""
    empty_pages = [
        {"url": "https://example.com", "error": "Failed to extract"},
    ]

    with (
        patch(
            "wet_mcp.sources.structured.raw_extract",
            new_callable=AsyncMock,
            return_value=json.dumps(empty_pages),
        ),
        patch("wet_mcp.sources.structured.settings") as mock_settings,
    ):
        mock_settings.resolve_provider_mode.return_value = "sdk"

        result_str = await extract_structured(
            urls=["https://example.com"],
            schema=SAMPLE_SCHEMA,
        )

        result = json.loads(result_str)
        assert "error" in result
        assert "No content" in result["error"]


async def test_extract_structured_validation_warning():
    """LLM returns JSON that doesn't fully match schema -- validation_warning present."""
    # Missing required "price" field
    llm_output = json.dumps({"title": "Widget"})

    with (
        patch(
            "wet_mcp.sources.structured.raw_extract",
            new_callable=AsyncMock,
            return_value=json.dumps(SAMPLE_PAGES),
        ),
        patch("wet_mcp.sources.structured.settings") as mock_settings,
        patch(
            "wet_mcp.sources.structured.get_llm_config",
            return_value={"model": "gpt-4", "fallbacks": None, "temperature": 0},
        ),
        patch(
            "wet_mcp.sources.structured.acompletion",
            new_callable=AsyncMock,
            return_value=_mock_llm_response(llm_output),
        ),
    ):
        mock_settings.resolve_provider_mode.return_value = "proxy"

        result_str = await extract_structured(
            urls=["https://example.com/product"],
            schema=SAMPLE_SCHEMA,
        )

        result = json.loads(result_str)
        assert "data" in result
        assert "validation_warning" in result
        assert "price" in result["validation_warning"]


async def test_extract_structured_fallback_to_json_object():
    """json_schema mode fails, json_object fallback succeeds."""
    llm_output = json.dumps({"title": "Widget", "price": 29.99})

    call_count = 0

    async def mock_acompletion(**kwargs):
        nonlocal call_count
        call_count += 1
        response_format = kwargs.get("response_format", {})
        if response_format.get("type") == "json_schema":
            raise Exception("json_schema not supported")
        return _mock_llm_response(llm_output)

    with (
        patch(
            "wet_mcp.sources.structured.raw_extract",
            new_callable=AsyncMock,
            return_value=json.dumps(SAMPLE_PAGES),
        ),
        patch("wet_mcp.sources.structured.settings") as mock_settings,
        patch(
            "wet_mcp.sources.structured.get_llm_config",
            return_value={"model": "gpt-4", "fallbacks": None, "temperature": 0},
        ),
        patch(
            "wet_mcp.sources.structured.acompletion",
            side_effect=mock_acompletion,
        ),
    ):
        mock_settings.resolve_provider_mode.return_value = "proxy"

        result_str = await extract_structured(
            urls=["https://example.com/product"],
            schema=SAMPLE_SCHEMA,
        )

        result = json.loads(result_str)
        assert "data" in result
        assert result["data"]["title"] == "Widget"
        assert call_count == 2  # first json_schema failed, second json_object succeeded


async def test_extract_structured_llm_failure():
    """Both LLM call modes fail -- returns error."""

    async def mock_acompletion(**kwargs):
        raise Exception("LLM unavailable")

    with (
        patch(
            "wet_mcp.sources.structured.raw_extract",
            new_callable=AsyncMock,
            return_value=json.dumps(SAMPLE_PAGES),
        ),
        patch("wet_mcp.sources.structured.settings") as mock_settings,
        patch(
            "wet_mcp.sources.structured.get_llm_config",
            return_value={"model": "gpt-4", "fallbacks": None, "temperature": 0},
        ),
        patch(
            "wet_mcp.sources.structured.acompletion",
            side_effect=mock_acompletion,
        ),
    ):
        mock_settings.resolve_provider_mode.return_value = "proxy"

        result_str = await extract_structured(
            urls=["https://example.com/product"],
            schema=SAMPLE_SCHEMA,
        )

        result = json.loads(result_str)
        assert "error" in result
        assert "LLM" in result["error"]
