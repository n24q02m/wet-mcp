"""Protocol contract for the tool names exposed by wet-mcp."""

import os

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

pytestmark = pytest.mark.timeout(60)

EXPECTED_NAMES = [
    "config",
    "config__open_relay",
    "extract",
    "help",
    "media",
    "search",
]
RETIRED_NAMES: list[str] = []


async def _list_tool_names() -> list[str]:
    params = StdioServerParameters(
        command="uv",
        args=["run", "wet-mcp"],
        env={
            **os.environ,
            "LOG_LEVEL": "WARNING",
            "DISABLE_LOCAL_EMBED": "true",
            "DISABLE_LOCAL_RERANK": "true",
            "DISABLE_LOCAL_SEARCH": "true",
            "WET_AUTO_SEARXNG": "false",
        },
    )
    async with stdio_client(params) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            return sorted(tool.name for tool in (await session.list_tools()).tools)


@pytest.mark.asyncio
async def test_exposes_exactly_the_names_from_the_protocol_contract():
    assert await _list_tool_names() == EXPECTED_NAMES


@pytest.mark.asyncio
async def test_no_retired_name_is_still_exposed():
    names = await _list_tool_names()
    assert not [name for name in RETIRED_NAMES if name in names]
