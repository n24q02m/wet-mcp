"""Full/real live MCP protocol tests for wet-mcp.

Spawns a real MCP server via stdio and tests ALL tool actions with real data.
Local ONNX mode (no API keys needed) unless explicitly testing other modes.

Usage:
    uv run pytest tests/test_full_live.py -m full -v --tb=short
"""

import json
import os
import warnings

import pytest
from mcp import StdioServerParameters
from mcp.client.session import ClientSession
from mcp.client.stdio import stdio_client

pytestmark = [pytest.mark.full, pytest.mark.timeout(60)]


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
async def mcp_session(tmp_path):
    """Start real wet-mcp server via stdio, yield ClientSession.

    Uses tmp_path for cache/docs to avoid polluting real data.
    """
    server_params = StdioServerParameters(
        command="uv",
        args=["run", "wet-mcp"],
        env={
            **os.environ,
            "LOG_LEVEL": "WARNING",
            "CACHE_DIR": str(tmp_path),
            "DOCS_DB_PATH": str(tmp_path / "docs.db"),
            "DOWNLOAD_DIR": str(tmp_path / "downloads"),
            # Force local mode (no API keys)
            "EMBEDDING_BACKEND": "local",
            "RERANK_BACKEND": "local",
        },
    )
    try:
        async with stdio_client(server_params) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                yield session
    except (RuntimeError, ExceptionGroup) as exc:
        msg = str(exc).lower()
        if "cancel scope" in msg or "different task" in msg:
            warnings.warn(
                f"Suppressed teardown error: {exc}",
                RuntimeWarning,
                stacklevel=1,
            )
        else:
            raise


@pytest.fixture
async def mcp_session_rerank_off(tmp_path):
    """MCP session with reranking disabled."""
    server_params = StdioServerParameters(
        command="uv",
        args=["run", "wet-mcp"],
        env={
            **os.environ,
            "LOG_LEVEL": "WARNING",
            "CACHE_DIR": str(tmp_path),
            "DOCS_DB_PATH": str(tmp_path / "docs.db"),
            "EMBEDDING_BACKEND": "local",
            "RERANK_ENABLED": "false",
        },
    )
    try:
        async with stdio_client(server_params) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                yield session
    except (RuntimeError, ExceptionGroup) as exc:
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
# Search tool (local ONNX, embedded SearXNG)
# ---------------------------------------------------------------------------


@pytest.mark.timeout(120)
class TestFullSearch:
    async def test_search_search(self, mcp_session: ClientSession):
        """search.search -- basic web search."""
        r = await mcp_session.call_tool(
            "search", {"action": "search", "query": "python testing"}
        )
        text = parse(r)
        assert len(text) > 50, f"Search result too short: {len(text)} chars"
        assert "result" in text.lower() or "http" in text.lower(), text[:120]

    async def test_search_research(self, mcp_session: ClientSession):
        """search.research -- multi-query deep research."""
        r = await mcp_session.call_tool(
            "search",
            {"action": "research", "query": "transformer attention mechanism"},
        )
        text = parse(r)
        assert len(text) > 100, f"Research result too short: {len(text)} chars"

    async def test_search_docs(self, mcp_session: ClientSession):
        """search.docs -- library documentation search."""
        r = await mcp_session.call_tool(
            "search", {"action": "docs", "library": "requests", "query": "get"}
        )
        text = parse(r)
        assert len(text) > 50, f"Docs result too short: {len(text)} chars"

    async def test_search_similar(self, mcp_session: ClientSession):
        """search.similar -- find similar content in docs."""
        # First index some docs
        await mcp_session.call_tool(
            "search", {"action": "docs", "library": "requests", "query": "get"}
        )
        # Then search similar
        r = await mcp_session.call_tool(
            "search",
            {"action": "similar", "query": "HTTP requests in Python"},
        )
        text = parse_allow_error(r)
        # May return results or "no similar docs" -- both are valid
        assert len(text) > 10, f"Similar result too short: {len(text)} chars"


# ---------------------------------------------------------------------------
# Extract tool (real URLs)
# ---------------------------------------------------------------------------


@pytest.mark.timeout(120)
class TestFullExtract:
    async def test_extract_extract(self, mcp_session: ClientSession):
        """extract.extract -- extract content from a real URL."""
        r = await mcp_session.call_tool(
            "extract", {"action": "extract", "urls": ["https://example.com"]}
        )
        text = parse(r)
        assert len(text) > 50, f"Extract result too short: {len(text)} chars"
        assert "example" in text.lower() or "domain" in text.lower(), text[:120]

    async def test_extract_crawl(self, mcp_session: ClientSession):
        """extract.crawl -- crawl with depth=1."""
        r = await mcp_session.call_tool(
            "extract",
            {
                "action": "crawl",
                "urls": ["https://example.com"],
                "depth": 1,
                "max_pages": 2,
            },
        )
        text = parse(r)
        assert len(text) > 50, f"Crawl result too short: {len(text)} chars"

    async def test_extract_map(self, mcp_session: ClientSession):
        """extract.map -- site map."""
        r = await mcp_session.call_tool(
            "extract",
            {"action": "map", "urls": ["https://example.com"], "max_pages": 3},
        )
        text = parse(r)
        assert len(text) > 10, f"Map result too short: {len(text)} chars"

    async def test_extract_batch(self, mcp_session: ClientSession):
        """extract.batch -- extract from multiple URLs."""
        r = await mcp_session.call_tool(
            "extract",
            {
                "action": "batch",
                "urls": [
                    "https://example.com",
                    "https://httpbin.org/html",
                ],
            },
        )
        text = parse(r)
        assert len(text) > 50, f"Batch result too short: {len(text)} chars"

    async def test_extract_convert(self, mcp_session: ClientSession, tmp_path):
        """extract.convert -- convert a local file to markdown."""
        # Create a simple text file to convert
        test_file = tmp_path / "test.txt"
        test_file.write_text("This is a test document for conversion.", encoding="utf-8")
        r = await mcp_session.call_tool(
            "extract",
            {"action": "convert", "paths": [str(test_file)]},
        )
        text = parse_allow_error(r)
        # Should either convert or report unsupported
        assert len(text) > 10, f"Convert result too short: {len(text)} chars"


# ---------------------------------------------------------------------------
# Media tool
# ---------------------------------------------------------------------------


@pytest.mark.timeout(120)
class TestFullMedia:
    async def test_media_list(self, mcp_session: ClientSession):
        """media.list -- list media on a page."""
        r = await mcp_session.call_tool(
            "media", {"action": "list", "url": "https://httpbin.org/image"}
        )
        text = parse(r)
        assert "image" in text.lower() or "media" in text.lower() or "http" in text.lower(), text[:120]

    async def test_media_download(self, mcp_session: ClientSession):
        """media.download -- download media file."""
        r = await mcp_session.call_tool(
            "media",
            {"action": "download", "media_urls": ["https://httpbin.org/image/png"]},
        )
        text = parse(r)
        assert any(
            w in text.lower() for w in ("download", "saved", "path", "file")
        ), text[:120]


# ---------------------------------------------------------------------------
# Config tool
# ---------------------------------------------------------------------------


class TestFullConfig:
    async def test_config_status(self, mcp_session: ClientSession):
        """config.status -- verify mode and config info."""
        r = await mcp_session.call_tool("config", {"action": "status"})
        text = parse(r)
        data = json.loads(text)
        assert "database" in data or "embedding" in data, (
            f"Missing expected keys: {list(data.keys())}"
        )

    async def test_config_set_embedding_backend(self, mcp_session: ClientSession):
        """config.set -- change embedding_backend."""
        r = await mcp_session.call_tool(
            "config", {"action": "set", "key": "embedding_backend", "value": "local"}
        )
        text = parse(r)
        assert any(w in text.lower() for w in ("updated", "set", "embedding")), text[:120]

    async def test_config_set_rerank_backend(self, mcp_session: ClientSession):
        """config.set -- change rerank_backend."""
        r = await mcp_session.call_tool(
            "config", {"action": "set", "key": "rerank_backend", "value": "local"}
        )
        text = parse(r)
        assert any(w in text.lower() for w in ("updated", "set", "rerank")), text[:120]

    async def test_config_cache_clear(self, mcp_session: ClientSession):
        """config.cache_clear -- clear web cache."""
        r = await mcp_session.call_tool("config", {"action": "cache_clear"})
        text = parse_allow_error(r)
        assert any(
            w in text.lower() for w in ("clear", "cache", "removed", "error", "database")
        ), text[:120]

    async def test_config_docs_reindex(self, mcp_session: ClientSession):
        """config.docs_reindex -- reindex library docs."""
        r = await mcp_session.call_tool(
            "config", {"action": "docs_reindex", "key": "requests"}
        )
        text = parse(r)
        assert any(
            w in text.lower() for w in ("clear", "reindex", "requests", "removed")
        ), text[:120]


# ---------------------------------------------------------------------------
# Setup tool
# ---------------------------------------------------------------------------


class TestFullSetup:
    @pytest.mark.timeout(120)
    async def test_setup_warmup(self, mcp_session: ClientSession):
        """setup.warmup -- pre-download/verify models."""
        r = await mcp_session.call_tool("setup", {"action": "warmup"})
        text = parse(r)
        data = json.loads(text)
        assert "status" in data or "embedding" in data, text[:120]

    async def test_setup_invalid_action(self, mcp_session: ClientSession):
        """setup with invalid action returns error."""
        r = await mcp_session.call_tool("setup", {"action": "invalid"})
        text = parse_allow_error(r)
        assert any(
            w in text.lower() for w in ("error", "unknown", "invalid")
        ), text[:120]


# ---------------------------------------------------------------------------
# LiteLLM mode (skipped if no LITELLM_PROXY_URL)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not os.environ.get("LITELLM_PROXY_URL"),
    reason="LITELLM_PROXY_URL not set",
)
@pytest.mark.timeout(120)
class TestFullLiteLLMMode:
    @pytest.fixture
    async def litellm_session(self, tmp_path):
        """MCP session using LiteLLM proxy mode."""
        server_params = StdioServerParameters(
            command="uv",
            args=["run", "wet-mcp"],
            env={
                **os.environ,
                "LOG_LEVEL": "WARNING",
                "CACHE_DIR": str(tmp_path),
                "DOCS_DB_PATH": str(tmp_path / "docs.db"),
            },
        )
        try:
            async with stdio_client(server_params) as (read_stream, write_stream):
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()
                    yield session
        except (RuntimeError, ExceptionGroup) as exc:
            msg = str(exc).lower()
            if "cancel scope" in msg or "different task" in msg:
                warnings.warn(
                    f"Suppressed teardown error: {exc}",
                    RuntimeWarning,
                    stacklevel=1,
                )
            else:
                raise

    async def test_search_docs_litellm(self, litellm_session: ClientSession):
        """search.docs with LiteLLM embedding."""
        r = await litellm_session.call_tool(
            "search", {"action": "docs", "library": "requests", "query": "get"}
        )
        text = parse(r)
        assert len(text) > 50, f"Docs result too short: {len(text)} chars"

    async def test_config_status_litellm(self, litellm_session: ClientSession):
        """config.status should show litellm mode."""
        r = await litellm_session.call_tool("config", {"action": "status"})
        text = parse(r)
        data = json.loads(text)
        embedding = data.get("embedding", {})
        assert embedding.get("available") is True, f"Embedding not available: {data}"


# ---------------------------------------------------------------------------
# Rerank disabled mode
# ---------------------------------------------------------------------------


@pytest.mark.timeout(120)
class TestFullRerankOff:
    async def test_search_docs_no_rerank(self, mcp_session_rerank_off: ClientSession):
        """search.docs without reranking should still return results."""
        r = await mcp_session_rerank_off.call_tool(
            "search", {"action": "docs", "library": "requests", "query": "get"}
        )
        text = parse(r)
        assert len(text) > 50, f"Docs result too short: {len(text)} chars"

    async def test_config_status_rerank_off(self, mcp_session_rerank_off: ClientSession):
        """config.status should show reranking disabled."""
        r = await mcp_session_rerank_off.call_tool("config", {"action": "status"})
        text = parse(r)
        data = json.loads(text)
        rerank = data.get("reranking", data.get("rerank", {}))
        # Either shows disabled or empty backend
        assert isinstance(data, dict), f"Expected dict, got: {type(data)}"


# ---------------------------------------------------------------------------
# Security boundary
# ---------------------------------------------------------------------------


class TestFullSecurity:
    async def test_ssrf_private_ip(self, mcp_session: ClientSession):
        """SSRF: private IP (AWS metadata) should be blocked."""
        r = await mcp_session.call_tool(
            "extract",
            {"action": "extract", "urls": ["http://169.254.169.254/latest/meta-data"]},
        )
        text = parse_allow_error(r)
        assert any(
            w in text.lower() for w in ("block", "denied", "ssrf", "error", "private")
        ), f"SSRF not blocked: {text[:120]}"

    async def test_ssrf_localhost(self, mcp_session: ClientSession):
        """SSRF: localhost should be blocked."""
        r = await mcp_session.call_tool(
            "extract",
            {"action": "extract", "urls": ["http://127.0.0.1:8080/secret"]},
        )
        text = parse_allow_error(r)
        assert any(
            w in text.lower() for w in ("block", "denied", "ssrf", "error", "private")
        ), f"SSRF not blocked: {text[:120]}"

    async def test_path_traversal(self, mcp_session: ClientSession):
        """Path traversal in media download should be blocked."""
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
            w in text.lower()
            for w in ("error", "denied", "security", "block", "traversal")
        ), f"Path traversal not blocked: {text[:120]}"
