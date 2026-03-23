"""Pytest-based live MCP protocol tests for wet-mcp.

Spawns a real MCP server via stdio and tests all tools through the protocol.
Config and help tests work offline. Network-dependent tests use the `network` marker.

Usage:
    uv run pytest tests/test_live_protocol.py -v --tb=short -m live
"""

import json
import os
import warnings

import pytest
from mcp import StdioServerParameters
from mcp.client.session import ClientSession
from mcp.client.stdio import stdio_client

pytestmark = [pytest.mark.live, pytest.mark.timeout(60)]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def parse(r) -> str:
    """Extract text from MCP tool result."""
    if hasattr(r, "isError") and r.isError:
        raise RuntimeError(r.content[0].text)
    return r.content[0].text


def parse_allow_error(r) -> str:
    """Extract text from MCP tool result, including error responses."""
    return r.content[0].text


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def mcp_session():
    """Start real wet-mcp server via stdio, yield ClientSession.

    Suppresses anyio cancel-scope teardown errors that occur when
    pytest-asyncio tears down the event loop in a different task context.
    """
    server_params = StdioServerParameters(
        command="uv",
        args=["run", "wet-mcp"],
        env={
            **os.environ,
            "LOG_LEVEL": "WARNING",
        },
    )
    try:
        async with stdio_client(server_params) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                yield session
    except (RuntimeError, ExceptionGroup) as exc:
        # anyio cancel-scope teardown error -- harmless in test context
        msg = str(exc).lower()
        if "cancel scope" in msg or "different task" in msg:
            warnings.warn(
                f"Suppressed teardown error: {exc}",
                RuntimeWarning,
                stacklevel=1,
            )
        else:
            raise


# ---------------------------------------------------------------------------
# Meta
# ---------------------------------------------------------------------------


class TestMeta:
    async def test_list_tools(self, mcp_session: ClientSession):
        result = await mcp_session.list_tools()
        tool_names = sorted(t.name for t in result.tools)
        expected = ["config", "extract", "help", "media", "search", "setup"]
        assert tool_names == expected, f"Expected {expected}, got {tool_names}"


# ---------------------------------------------------------------------------
# Help tool (offline)
# ---------------------------------------------------------------------------


class TestHelp:
    @pytest.mark.parametrize("topic", ["search", "extract", "media", "config", "help"])
    async def test_help_topics(self, mcp_session: ClientSession, topic: str):
        r = await mcp_session.call_tool("help", {"tool_name": topic})
        text = parse(r)
        assert len(text) >= 100, f"Help for '{topic}' too short: {len(text)} chars"

    async def test_help_invalid_topic(self, mcp_session: ClientSession):
        r = await mcp_session.call_tool("help", {"tool_name": "nonexistent"})
        text = parse_allow_error(r)
        assert any(w in text.lower() for w in ("error", "not found", "unknown")), (
            f"Expected error response, got: {text[:80]}"
        )


# ---------------------------------------------------------------------------
# Config tool (offline)
# ---------------------------------------------------------------------------


class TestConfig:
    async def test_config_status(self, mcp_session: ClientSession):
        r = await mcp_session.call_tool("config", {"action": "status"})
        text = parse(r)
        data = json.loads(text)
        assert "database" in data and "embedding" in data, (
            f"Missing expected keys: {list(data.keys())}"
        )

    async def test_config_set(self, mcp_session: ClientSession):
        r = await mcp_session.call_tool(
            "config", {"action": "set", "key": "log_level", "value": "DEBUG"}
        )
        text = parse(r)
        assert any(w in text.lower() for w in ("updated", "set")), text[:80]

    async def test_config_cache_clear(self, mcp_session: ClientSession):
        r = await mcp_session.call_tool("config", {"action": "cache_clear"})
        text = parse_allow_error(r)
        # May fail with "database is locked" if warmup is still running
        assert any(
            w in text.lower() for w in ("clear", "cache", "database", "error")
        ), text[:80]

    async def test_config_docs_reindex(self, mcp_session: ClientSession):
        r = await mcp_session.call_tool(
            "config", {"action": "docs_reindex", "key": "fastapi"}
        )
        text = parse(r)
        assert any(w in text.lower() for w in ("clear", "reindex", "fastapi")), text[
            :80
        ]

    async def test_config_set_invalid_key(self, mcp_session: ClientSession):
        r = await mcp_session.call_tool(
            "config", {"action": "set", "key": "invalid_key", "value": "x"}
        )
        text = parse_allow_error(r)
        assert any(w in text.lower() for w in ("error", "invalid", "valid")), (
            f"Expected error for invalid key, got: {text[:80]}"
        )


# ---------------------------------------------------------------------------
# Setup tool (offline -- warmup only)
# ---------------------------------------------------------------------------


class TestSetup:
    async def test_setup_warmup(self, mcp_session: ClientSession):
        r = await mcp_session.call_tool("setup", {"action": "warmup"})
        text = parse(r)
        data = json.loads(text)
        assert "status" in data or "error" not in data, text[:120]

    async def test_setup_invalid_action(self, mcp_session: ClientSession):
        r = await mcp_session.call_tool("setup", {"action": "invalid"})
        text = parse_allow_error(r)
        assert any(w in text.lower() for w in ("error", "unknown", "invalid")), text[
            :80
        ]


# ---------------------------------------------------------------------------
# Error paths (offline)
# ---------------------------------------------------------------------------


class TestErrorPaths:
    async def test_search_missing_query(self, mcp_session: ClientSession):
        r = await mcp_session.call_tool("search", {"action": "search"})
        text = parse_allow_error(r)
        assert any(w in text.lower() for w in ("error", "query", "required")), (
            f"Expected error, got: {text[:80]}"
        )

    async def test_search_invalid_action(self, mcp_session: ClientSession):
        r = await mcp_session.call_tool(
            "search", {"action": "invalid", "query": "test"}
        )
        text = parse_allow_error(r)
        assert any(w in text.lower() for w in ("error", "unknown", "invalid")), (
            f"Expected error, got: {text[:80]}"
        )

    async def test_extract_missing_urls(self, mcp_session: ClientSession):
        r = await mcp_session.call_tool("extract", {"action": "extract"})
        text = parse_allow_error(r)
        assert any(w in text.lower() for w in ("error", "url", "required")), (
            f"Expected error, got: {text[:80]}"
        )

    async def test_media_missing_url(self, mcp_session: ClientSession):
        r = await mcp_session.call_tool("media", {"action": "list"})
        text = parse_allow_error(r)
        assert any(w in text.lower() for w in ("error", "url", "required")), (
            f"Expected error, got: {text[:80]}"
        )


# ---------------------------------------------------------------------------
# Security boundary (offline)
# ---------------------------------------------------------------------------


class TestSecurity:
    async def test_ssrf_private_ip(self, mcp_session: ClientSession):
        r = await mcp_session.call_tool(
            "extract",
            {"action": "extract", "urls": ["http://169.254.169.254/latest/meta-data"]},
        )
        text = parse_allow_error(r)
        assert any(w in text.lower() for w in ("block", "denied", "ssrf", "error")), (
            f"SSRF not blocked: {text[:80]}"
        )

    async def test_ssrf_localhost(self, mcp_session: ClientSession):
        r = await mcp_session.call_tool(
            "extract",
            {"action": "extract", "urls": ["http://127.0.0.1:8080/secret"]},
        )
        text = parse_allow_error(r)
        assert any(w in text.lower() for w in ("block", "denied", "ssrf", "error")), (
            f"SSRF not blocked: {text[:80]}"
        )

    async def test_media_path_traversal(self, mcp_session: ClientSession):
        r = await mcp_session.call_tool(
            "media",
            {
                "action": "download",
                "media_urls": ["https://httpbin.org/image/png"],
                "output_dir": "/tmp/evil/../../../etc",
            },
        )
        text = parse_allow_error(r)
        assert any(
            w in text.lower() for w in ("error", "denied", "security", "block")
        ), f"Path traversal not blocked: {text[:80]}"


# ---------------------------------------------------------------------------
# Network-dependent tests (search, extract, media)
# ---------------------------------------------------------------------------


@pytest.mark.network
@pytest.mark.timeout(120)
class TestSearch:
    async def test_search_search(self, mcp_session: ClientSession):
        r = await mcp_session.call_tool(
            "search", {"action": "search", "query": "python testing"}
        )
        text = parse(r)
        assert "result" in text.lower() or "http" in text.lower(), text[:80]

    async def test_search_research(self, mcp_session: ClientSession):
        r = await mcp_session.call_tool(
            "search",
            {"action": "research", "query": "transformer attention mechanism"},
        )
        text = parse(r)
        assert len(text) > 50, f"Research result too short: {len(text)} chars"

    async def test_search_docs(self, mcp_session: ClientSession):
        r = await mcp_session.call_tool(
            "search", {"action": "docs", "library": "requests", "query": "get"}
        )
        text = parse(r)
        assert len(text) > 50, f"Docs result too short: {len(text)} chars"


@pytest.mark.network
@pytest.mark.timeout(120)
class TestExtract:
    async def test_extract_extract(self, mcp_session: ClientSession):
        r = await mcp_session.call_tool(
            "extract", {"action": "extract", "urls": ["https://httpbin.org/html"]}
        )
        text = parse(r)
        assert len(text) > 100, f"Extract result too short: {len(text)} chars"

    async def test_extract_crawl(self, mcp_session: ClientSession):
        r = await mcp_session.call_tool(
            "extract",
            {
                "action": "crawl",
                "urls": ["https://docs.python.org/3/library/json.html"],
                "depth": 1,
                "max_pages": 2,
            },
        )
        text = parse(r)
        assert len(text) > 100, f"Crawl result too short: {len(text)} chars"

    async def test_extract_map(self, mcp_session: ClientSession):
        r = await mcp_session.call_tool(
            "extract",
            {"action": "map", "urls": ["https://docs.python.org/3/"], "max_pages": 5},
        )
        text = parse(r)
        assert "http" in text.lower() or "url" in text.lower(), text[:80]


@pytest.mark.network
@pytest.mark.timeout(120)
class TestMedia:
    async def test_media_list(self, mcp_session: ClientSession):
        r = await mcp_session.call_tool(
            "media", {"action": "list", "url": "https://httpbin.org/image"}
        )
        text = parse(r)
        assert "image" in text.lower() or "media" in text.lower(), text[:80]

    async def test_media_download(self, mcp_session: ClientSession):
        r = await mcp_session.call_tool(
            "media",
            {"action": "download", "media_urls": ["https://httpbin.org/image/png"]},
        )
        text = parse(r)
        assert any(w in text.lower() for w in ("download", "path", "file")), text[:80]

    async def test_media_analyze_no_key(self, mcp_session: ClientSession):
        """media.analyze without API keys should fail gracefully."""
        r = await mcp_session.call_tool(
            "media",
            {"action": "analyze", "url": "/tmp/nonexistent.png", "prompt": "describe"},
        )
        text = parse_allow_error(r)
        # Should error about missing API key or file not found
        assert any(w in text.lower() for w in ("api", "key", "error", "not found")), (
            text[:80]
        )
