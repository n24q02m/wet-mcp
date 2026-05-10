"""Server-level dispatch tests for ``extract(action="agent")`` (Phase 3 Task 2)."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest

from wet_mcp.server import extract


@pytest.mark.asyncio
async def test_agent_action_missing_query_returns_error() -> None:
    result = await extract(action="agent")
    assert isinstance(result, str)
    assert "query is required" in result


@pytest.mark.asyncio
async def test_agent_action_routes_to_orchestrator_and_serialises_dict() -> None:
    fake_result = {
        "markdown": "synth",
        "sources": [{"index": 1, "url": "https://x", "title": "t"}],
        "per_url_metadata": [
            {"url": "https://x", "extract_strategy": "basic_http", "tokens": 10}
        ],
    }
    with patch(
        "wet_mcp.sources.agent_orchestrator.run_agent",
        new_callable=AsyncMock,
        return_value=fake_result,
    ):
        result = await extract(action="agent", query="explain X")
    # _wrap_tool wraps non-error responses in <untrusted_extract_content>
    # tags; the JSON payload is embedded inside.
    assert isinstance(result, str)
    assert "<untrusted_extract_content>" in result
    assert '"markdown": "synth"' in result
    assert '"url": "https://x"' in result
    # Extract the JSON body and round-trip parse to confirm validity.
    body = (
        result.split("<untrusted_extract_content>", 1)[1]
        .split("</untrusted_extract_content>", 1)[0]
        .strip()
    )
    # The wrapper may also tail-append a security warning; locate the
    # JSON document boundary via balanced braces.
    body = body[body.index("{") : body.rindex("}") + 1]
    payload = json.loads(body)
    assert payload["sources"][0]["url"] == "https://x"


@pytest.mark.asyncio
async def test_agent_action_passes_through_error_string() -> None:
    with patch(
        "wet_mcp.sources.agent_orchestrator.run_agent",
        new_callable=AsyncMock,
        return_value="Error: no LLM provider detected. ...",
    ):
        result = await extract(action="agent", query="x")
    assert isinstance(result, str)
    assert result.startswith("Error: no LLM provider detected")


@pytest.mark.asyncio
async def test_agent_listed_in_unknown_action_help() -> None:
    result = await extract(action="bogus_action_99")
    assert isinstance(result, str)
    assert "agent" in result, "agent should appear in valid actions list"
