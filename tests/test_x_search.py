"""Unit + integration tests for search(action="x") — X/Twitter via xAI.

Unit tests mock ``litellm.aresponses`` and assert SHAPE (param mapping,
annotation->citations parse, cost math, XPIA marker, error paths) — never X
content, which changes constantly. The single integration test makes one real
call (marked, excluded from the default run) and asserts an X citation shows up
under a cost ceiling.
"""

import re
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from wet_mcp.sources.x_search import (
    _estimate_cost,
    _resolve_dates,
    build_x_search_tool,
    resolve_model,
    run_x_search,
    x_search_status,
)

# --- fake Responses-API objects -------------------------------------------


def _annotation(url, title, start, end):
    return SimpleNamespace(
        type="url_citation",
        url=url,
        title=title,
        start_index=start,
        end_index=end,
    )


def _fake_response(answer, citations, input_tokens, output_tokens, n_tool_calls):
    """Mimic litellm's ResponsesAPIResponse: reasoning + tool-call items, then
    a message whose output_text block carries the citations as annotations."""
    anns = [_annotation(*c) for c in citations]
    message = SimpleNamespace(
        type="message",
        content=[SimpleNamespace(type="output_text", text=answer, annotations=anns)],
    )
    output = [SimpleNamespace(type="custom_tool_call") for _ in range(n_tool_calls)]
    output.append(message)
    usage = SimpleNamespace(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=input_tokens + output_tokens,
    )
    return SimpleNamespace(
        output=output, usage=usage, output_text=answer, model="grok-4.3"
    )


@pytest.fixture
def xai_key(monkeypatch):
    monkeypatch.setenv("XAI_API_KEY", "test-key-not-real")
    monkeypatch.delenv("X_SEARCH_MODEL", raising=False)


# --- build_x_search_tool: param mapping -----------------------------------


def test_build_tool_maps_handles():
    tool = build_x_search_tool(["nasa", "esa"], None, None, None, None, 10, False)
    assert tool["type"] == "x_search"
    assert tool["allowed_x_handles"] == ["nasa", "esa"]
    assert "excluded_x_handles" not in tool


def test_build_tool_maps_exclude_handles():
    tool = build_x_search_tool(None, ["spam"], None, None, None, 10, False)
    assert tool["excluded_x_handles"] == ["spam"]
    assert "allowed_x_handles" not in tool


def test_build_tool_handles_mutually_exclusive():
    with pytest.raises(ValueError, match="mutually exclusive"):
        build_x_search_tool(["a"], ["b"], None, None, None, 10, False)


def test_build_tool_handles_max_20():
    too_many = [f"h{i}" for i in range(21)]
    with pytest.raises(ValueError, match="at most 20"):
        build_x_search_tool(too_many, None, None, None, None, 10, False)


def test_build_tool_exclude_handles_max_20():
    too_many = [f"h{i}" for i in range(21)]
    with pytest.raises(ValueError, match="at most 20"):
        build_x_search_tool(None, too_many, None, None, None, 10, False)


def test_build_tool_max_results_and_video():
    tool = build_x_search_tool(None, None, None, None, None, 7, True)
    assert tool["max_search_results"] == 7
    assert tool["enable_video_understanding"] is True


def test_build_tool_video_off_omits_flag():
    tool = build_x_search_tool(None, None, None, None, None, 10, False)
    assert "enable_video_understanding" not in tool


# --- date resolution -------------------------------------------------------


def test_resolve_dates_time_range_week_is_iso8601_7_day_window():
    fd, td = _resolve_dates("week", None, None)
    assert fd and td
    parsed_from = date.fromisoformat(fd)  # raises if not ISO8601
    parsed_to = date.fromisoformat(td)
    assert (parsed_to - parsed_from).days == 7


@pytest.mark.parametrize(
    "rng,days", [("day", 1), ("week", 7), ("month", 30), ("year", 365)]
)
def test_resolve_dates_all_ranges(rng, days):
    fd, td = _resolve_dates(rng, None, None)
    assert fd and td
    assert (date.fromisoformat(td) - date.fromisoformat(fd)).days == days


def test_resolve_dates_explicit_overrides_time_range():
    fd, td = _resolve_dates("week", "2025-01-01", "2025-01-05")
    assert (fd, td) == ("2025-01-01", "2025-01-05")


def test_resolve_dates_none_when_no_filter():
    assert _resolve_dates(None, None, None) == (None, None)


def test_build_tool_maps_time_range_to_dates():
    tool = build_x_search_tool(None, None, "month", None, None, 10, False)
    assert "from_date" in tool and "to_date" in tool
    assert (
        date.fromisoformat(str(tool["to_date"]))
        - date.fromisoformat(str(tool["from_date"]))
    ).days == 30


# --- cost estimate (reproduces the spec probe table) -----------------------


def test_estimate_cost_grok_43_matches_probe():
    # 10,613 in + 1,376 out + 3 tool calls -> spec table ~$0.032
    assert _estimate_cost("grok-4.3", 10613, 1376, 3) == 0.0317


def test_estimate_cost_grok_45_matches_probe():
    # 39,286 in + 3,289 out + 5 tool calls -> spec table ~$0.12
    assert _estimate_cost("grok-4.5", 39286, 3289, 5) == 0.1233


def test_estimate_cost_unknown_model_falls_back_to_default_pricing():
    assert _estimate_cost("grok-9.9", 10613, 1376, 3) == _estimate_cost(
        "grok-4.3", 10613, 1376, 3
    )


# --- resolve_model / status ------------------------------------------------


def test_resolve_model_default(monkeypatch):
    monkeypatch.delenv("X_SEARCH_MODEL", raising=False)
    assert resolve_model() == "grok-4.3"


def test_resolve_model_override(monkeypatch):
    monkeypatch.setenv("X_SEARCH_MODEL", "grok-4.5")
    assert resolve_model() == "grok-4.5"


def test_x_search_status_reflects_key_and_model(monkeypatch):
    monkeypatch.setenv("XAI_API_KEY", "k")
    monkeypatch.setenv("X_SEARCH_MODEL", "grok-4.5")
    status = x_search_status()
    assert status == {"xai_api_key_set": True, "model": "grok-4.5"}

    monkeypatch.delenv("XAI_API_KEY", raising=False)
    assert x_search_status()["xai_api_key_set"] is False


# --- run_x_search: error paths --------------------------------------------


async def test_missing_key_returns_clear_error(monkeypatch):
    monkeypatch.delenv("XAI_API_KEY", raising=False)
    result = await run_x_search(query="anything")
    assert result == {"error": "Error: XAI_API_KEY not set. Get one at console.x.ai"}


async def test_bad_params_return_error_dict(xai_key):
    result = await run_x_search(query="q", handles=["a"], exclude_handles=["b"])
    assert result["error"].startswith("Error:")
    assert "mutually exclusive" in result["error"]


async def test_upstream_failure_returns_error_dict(xai_key):
    with patch(
        "litellm.aresponses", new_callable=AsyncMock, side_effect=RuntimeError("boom")
    ):
        result = await run_x_search(query="q")
    assert result["error"].startswith("Error: x_search request failed:")


# --- run_x_search: happy path (annotation parse, usage, cost, marker) ------


async def test_run_x_search_parses_citations_usage_and_source(xai_key):
    fake = _fake_response(
        answer="Answer with [[1]](https://x.com/a/status/1).",
        citations=[
            ("https://x.com/a/status/1", "1", 12, 40),
            ("https://x.com/b/status/2", "2", 41, 60),
        ],
        input_tokens=10613,
        output_tokens=1376,
        n_tool_calls=3,
    )
    with patch(
        "litellm.aresponses", new_callable=AsyncMock, return_value=fake
    ) as mock_call:
        result = await run_x_search(
            query="q", handles=["a"], time_range="week", video=True, max_results=8
        )

    # Citations parsed from annotations (NOT response.citations).
    assert result["citations"] == [
        {
            "url": "https://x.com/a/status/1",
            "title": "1",
            "start_index": 12,
            "end_index": 40,
        },
        {
            "url": "https://x.com/b/status/2",
            "title": "2",
            "start_index": 41,
            "end_index": 60,
        },
    ]
    assert result["answer"].startswith("Answer with")
    assert result["model"] == "grok-4.3"
    assert result["usage"] == {
        "input_tokens": 10613,
        "output_tokens": 1376,
        "tool_calls": 3,
        "estimated_cost_usd": 0.0317,
    }
    # XPIA source hint threaded to the wrapper.
    assert result["_source"] == "x"

    # The tool config sent upstream carries the mapped params.
    tool = mock_call.call_args.kwargs["tools"][0]
    assert tool["allowed_x_handles"] == ["a"]
    assert tool["max_search_results"] == 8
    assert tool["enable_video_understanding"] is True
    assert "from_date" in tool and "to_date" in tool
    # model + key forwarded correctly.
    assert mock_call.call_args.kwargs["model"] == "xai/grok-4.3"
    assert mock_call.call_args.kwargs["api_key"] == "test-key-not-real"


async def test_run_x_search_empty_annotations_yields_no_citations(xai_key):
    fake = _fake_response("No posts found.", [], 3000, 500, 1)
    with patch("litellm.aresponses", new_callable=AsyncMock, return_value=fake):
        result = await run_x_search(query="q")
    assert result["citations"] == []
    assert result["usage"]["tool_calls"] == 1


# --- multi-user: sub-aware key resolution (finding #5 cost/abuse guard) -----


async def test_multi_user_sub_uses_own_xai_key():
    """A sub whose per-sub bucket holds an XAI key: x proceeds with THAT key,
    not the process env / operator key."""
    fake = _fake_response(
        "ans", [("https://x.com/a/status/1", "1", 0, 2)], 3000, 400, 1
    )
    with (
        patch(
            "wet_mcp.credential_state.credentials_for_current_request",
            return_value={"XAI_API_KEY": "sub-owned-key"},
        ),
        patch(
            "litellm.aresponses", new_callable=AsyncMock, return_value=fake
        ) as mock_call,
    ):
        result = await run_x_search(query="q")

    assert "error" not in result, result
    assert mock_call.call_args.kwargs["api_key"] == "sub-owned-key"


async def test_multi_user_empty_vault_sub_errors_and_makes_no_api_call():
    """A sub with an EMPTY vault must NOT spend the operator's key: it gets the
    clean "not set" error and litellm is never called. This is the guard against
    a zero-setup sub burning the operator's shared XAI budget on the live
    multi-user endpoint."""
    with (
        patch(
            "wet_mcp.credential_state.credentials_for_current_request",
            return_value={},
        ),
        patch("litellm.aresponses", new_callable=AsyncMock) as mock_call,
    ):
        result = await run_x_search(query="q")

    assert result == {"error": "Error: XAI_API_KEY not set. Get one at console.x.ai"}
    mock_call.assert_not_called()


# --- server tool wiring: XPIA envelope carries _untrusted_source: "x" ------


async def test_x_action_marks_envelope_source_x(xai_key):
    """search(action="x") must stamp the XPIA envelope with source 'x' on BOTH
    channels — proving the _source hint survives _wrap_tool."""
    import importlib

    from mcp.types import CallToolResult
    from structured import payload, text

    server = importlib.import_module("wet_mcp.server")
    xpayload = {
        "answer": "hi",
        "citations": [
            {
                "url": "https://x.com/a/status/1",
                "title": "1",
                "start_index": 0,
                "end_index": 2,
            }
        ],
        "model": "grok-4.3",
        "usage": {
            "input_tokens": 1,
            "output_tokens": 1,
            "tool_calls": 1,
            "estimated_cost_usd": 0.01,
        },
        "_source": "x",
    }
    with patch(
        "wet_mcp.sources.x_search.run_x_search",
        new_callable=AsyncMock,
        return_value=xpayload,
    ):
        result = await server.search(action="x", query="q")

    assert isinstance(result, CallToolResult)
    data = payload(result)
    assert data["_untrusted_source"] == "x"
    assert data["answer"] == "hi"
    # The internal hint is consumed, not leaked to the client.
    assert "_source" not in data
    assert "<untrusted_search_content>" in text(result)


async def test_x_action_requires_query():
    import importlib

    from structured import payload

    server = importlib.import_module("wet_mcp.server")
    result = await server.search(action="x")
    assert payload(result)["error"].startswith("Error: query is required for x action")


# --- integration (real xAI call; excluded from the default run) ------------


@pytest.mark.integration
@pytest.mark.timeout(120)
async def test_x_search_live_returns_x_citations_under_cost_ceiling():
    import os

    if not os.getenv("XAI_API_KEY"):
        pytest.skip("XAI_API_KEY not set (skret /wet-mcp/prod)")

    result = await run_x_search(
        query="What are people on X saying about AI this week?",
        time_range="week",
        max_results=5,
    )
    assert "error" not in result, result
    assert result["citations"], "expected at least one citation"
    assert any(
        re.match(r"^https://x\.com/", str(c["url"] or "")) for c in result["citations"]
    ), result["citations"]
    # Guards an expensive model silently slipping into the default path.
    assert result["usage"]["estimated_cost_usd"] < 0.10, result["usage"]
