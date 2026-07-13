"""X/Twitter search via xAI's Agent Tools (the ``x_search`` server-side tool).

Transport note (verified 2026-07-12, spike with the skret ``/wet-mcp/prod``
key): xAI only accepts ``tools=[{"type": "x_search"}]`` on the ``/v1/responses``
endpoint. The ``/chat/completions`` endpoint that ``mcp_core.llm.acompletion``
wraps rejects it (``unknown variant 'x_search', expected 'function' or
'live_search'``). ``litellm.aresponses`` forwards the server tool through the
Responses endpoint and returns the same ``ResponsesAPIResponse`` /
``AnnotationURLCitation`` shape as the raw OpenAI SDK, so we stay on the repo's
litellm dispatch and add no direct provider SDK dependency.

Citations trap: ``response.citations`` is absent on this path (xAI advertises it
only for its native gRPC SDK). The real citations live in the ``annotations`` of
the ``output_text`` content block — parse them from there.
"""

import os
from datetime import UTC, datetime, timedelta
from typing import Any

from loguru import logger

_DEFAULT_MODEL = "grok-4.3"
_MAX_HANDLES = 20

# Cost model (reproduces the spec's probe table). Per-token prices come from
# xAI's published rates (mirrored in litellm's model_cost 2026-07); the
# server-tool fee is xAI Agent Tools' flat $5 / 1000 tool calls.
_TOOL_CALL_COST_USD = 0.005
_MODEL_PRICING: dict[str, tuple[float, float]] = {
    # model: (input $/token, output $/token)
    "grok-4.3": (1.25e-6, 2.5e-6),
    "grok-4.5": (2e-6, 6e-6),
}

# time_range -> lookback window used to derive from_date/to_date.
_TIME_RANGE_DAYS = {"day": 1, "week": 7, "month": 30, "year": 365}


def resolve_model() -> str:
    """The X-search model: ``X_SEARCH_MODEL`` env override, else grok-4.3."""
    return os.getenv("X_SEARCH_MODEL") or _DEFAULT_MODEL


def x_search_status() -> dict[str, Any]:
    """Whether the X-search feature is usable + which model it will bill.

    Consumed by ``config(action="status")`` so the operator can see, before
    spending money, that the key is present and whether they are on the cheap
    ($0.032/query) or the expensive ($0.12/query) model.
    """
    return {
        "xai_api_key_set": bool(os.getenv("XAI_API_KEY")),
        "model": resolve_model(),
    }


def _resolve_dates(
    time_range: str | None,
    from_date: str | None,
    to_date: str | None,
) -> tuple[str | None, str | None]:
    """Resolve the ISO8601 (from_date, to_date) window.

    Explicit ``from_date`` / ``to_date`` win; otherwise ``time_range`` maps to
    a lookback window ending today. No time filter -> (None, None).
    """
    if from_date or to_date:
        return from_date, to_date
    days = _TIME_RANGE_DAYS.get(time_range or "")
    if days is None:
        return None, None
    today = datetime.now(UTC).date()
    return (today - timedelta(days=days)).isoformat(), today.isoformat()


def build_x_search_tool(
    handles: list[str] | None,
    exclude_handles: list[str] | None,
    time_range: str | None,
    from_date: str | None,
    to_date: str | None,
    max_results: int,
    video: bool,
) -> dict[str, Any]:
    """Build the ``x_search`` tool-config object for the Responses API.

    Raises ``ValueError`` on invalid params (mutually-exclusive handle lists,
    more than 20 handles) so the caller can turn it into an error dict.
    """
    if handles and exclude_handles:
        raise ValueError("handles and exclude_handles are mutually exclusive")

    tool: dict[str, Any] = {"type": "x_search"}
    if handles:
        if len(handles) > _MAX_HANDLES:
            raise ValueError(f"handles accepts at most {_MAX_HANDLES} entries")
        tool["allowed_x_handles"] = handles
    if exclude_handles:
        if len(exclude_handles) > _MAX_HANDLES:
            raise ValueError(f"exclude_handles accepts at most {_MAX_HANDLES} entries")
        tool["excluded_x_handles"] = exclude_handles

    fd, td = _resolve_dates(time_range, from_date, to_date)
    if fd:
        tool["from_date"] = fd
    if td:
        tool["to_date"] = td
    if max_results:
        tool["max_search_results"] = max_results
    if video:
        tool["enable_video_understanding"] = True
    return tool


def _parse_citations(resp: object) -> list[dict[str, Any]]:
    """Pull citations from the ``output_text`` annotations (the real source)."""
    citations: list[dict[str, Any]] = []
    for item in getattr(resp, "output", []) or []:
        if getattr(item, "type", None) != "message":
            continue
        for block in getattr(item, "content", []) or []:
            if getattr(block, "type", None) != "output_text":
                continue
            for ann in getattr(block, "annotations", None) or []:
                citations.append(
                    {
                        "url": getattr(ann, "url", None),
                        "title": getattr(ann, "title", None),
                        "start_index": getattr(ann, "start_index", None),
                        "end_index": getattr(ann, "end_index", None),
                    }
                )
    return citations


def _count_tool_calls(resp: object) -> int:
    """Count server-tool invocations (``custom_tool_call`` output items)."""
    return sum(
        1
        for item in getattr(resp, "output", []) or []
        if "call" in (getattr(item, "type", "") or "")
    )


def _extract_answer(resp: object) -> str:
    """The synthesized markdown answer (with inline ``[[N]](url)`` citations)."""
    text = getattr(resp, "output_text", None)
    if text:
        return text
    parts: list[str] = []
    for item in getattr(resp, "output", []) or []:
        if getattr(item, "type", None) != "message":
            continue
        for block in getattr(item, "content", []) or []:
            if getattr(block, "type", None) == "output_text":
                parts.append(getattr(block, "text", "") or "")
    return "".join(parts)


def _estimate_cost(
    model: str, input_tokens: int, output_tokens: int, tool_calls: int
) -> float:
    """Estimate $/query: token cost + server-tool fee. Unknown model -> grok-4.3."""
    in_price, out_price = _MODEL_PRICING.get(model, _MODEL_PRICING[_DEFAULT_MODEL])
    cost = (
        input_tokens * in_price
        + output_tokens * out_price
        + tool_calls * _TOOL_CALL_COST_USD
    )
    return round(cost, 4)


async def run_x_search(
    query: str,
    handles: list[str] | None = None,
    exclude_handles: list[str] | None = None,
    time_range: str | None = None,
    from_date: str | None = None,
    to_date: str | None = None,
    max_results: int = 10,
    video: bool = False,
) -> dict[str, Any]:
    """Search X/Twitter via xAI and return a synthesized answer + citations.

    Returns a dict ``{answer, citations, model, usage, _source}`` on success, or
    ``{"error": ...}`` on a missing key / bad params / upstream failure. The
    ``_source: "x"`` hint tells the tool wrapper to stamp the XPIA envelope with
    ``_untrusted_source: "x"`` (X posts are external content written by
    strangers — a classic prompt-injection vector).
    """
    api_key = os.getenv("XAI_API_KEY")
    if not api_key:
        return {"error": "Error: XAI_API_KEY not set. Get one at console.x.ai"}

    try:
        tool = build_x_search_tool(
            handles, exclude_handles, time_range, from_date, to_date, max_results, video
        )
    except ValueError as exc:
        return {"error": f"Error: {exc}"}

    model = resolve_model()

    # Lazy import: litellm costs ~1-2s on first import (matches wet_mcp.llm).
    import litellm

    try:
        resp = await litellm.aresponses(
            model=f"xai/{model}",
            input=query,
            tools=[tool],
            api_key=api_key,
        )
    except Exception as exc:
        logger.error(f"x_search request failed: {exc}")
        return {"error": f"Error: x_search request failed: {exc}"}

    citations = _parse_citations(resp)
    usage = getattr(resp, "usage", None)
    input_tokens = int(getattr(usage, "input_tokens", 0) or 0)
    output_tokens = int(getattr(usage, "output_tokens", 0) or 0)
    tool_calls = _count_tool_calls(resp)
    estimated_cost_usd = _estimate_cost(model, input_tokens, output_tokens, tool_calls)

    logger.info(
        f"x_search model={model} est_cost=${estimated_cost_usd} "
        f"(in={input_tokens} out={output_tokens} tool_calls={tool_calls} "
        f"citations={len(citations)})"
    )

    return {
        "answer": _extract_answer(resp),
        "citations": citations,
        "model": model,
        "usage": {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "tool_calls": tool_calls,
            "estimated_cost_usd": estimated_cost_usd,
        },
        "_source": "x",
    }
