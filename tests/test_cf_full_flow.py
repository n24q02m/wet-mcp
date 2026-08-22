"""Tests for the Wet hosted protocol benchmark harness."""

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.cf_full_flow import _assert_extract_resolved, _run_extract


def test_assert_extract_resolved_accepts_real_markdown_result():
    _assert_extract_resolved(
        '{"results":[{"url":"https://example.com","markdown":"# Example\n\ncontent"}]}'
    )


@pytest.mark.asyncio
async def test_run_extract_calls_extract_domain_tool():
    class FakeSession:
        async def call_tool(self, tool, args):
            assert tool == "extract"
            assert args["action"] == "extract"
            return SimpleNamespace(
                content=[
                    SimpleNamespace(
                        text='{"results":[{"url":"https://example.com","markdown":"content"}]}'
                    )
                ]
            )

    text = await _run_extract(FakeSession())
    _assert_extract_resolved(text)
