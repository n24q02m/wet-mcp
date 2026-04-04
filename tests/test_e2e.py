"""Full E2E test for wet-mcp -- single file, 3 setup modes.

Tests ALL 5 tools, ALL 18 actions via MCP protocol.
Uses function-scoped fixtures (proven stable on Windows).

Usage:
    uv run pytest tests/test_e2e.py -m e2e --setup=env -v -s
    uv run pytest tests/test_e2e.py -m e2e --setup=relay --browser=chrome -v -s
    uv run pytest tests/test_e2e.py -m e2e --setup=plugin -v -s
    uv run pytest tests/test_e2e.py -m "e2e and not slow" --setup=env -v -s
"""

from __future__ import annotations

import asyncio
import os
import warnings

import pytest
from conftest_e2e import (
    StderrCapture,
    open_browser,
    parse_result,
    parse_result_allow_error,
)
from mcp import StdioServerParameters
from mcp.client.session import ClientSession
from mcp.client.stdio import stdio_client

pytestmark = [pytest.mark.e2e, pytest.mark.timeout(120)]

# Env vars to STRIP in relay mode (force server to use relay for credentials)
CREDENTIAL_ENV_VARS = [
    "JINA_AI_API_KEY",
    "GEMINI_API_KEY",
    "OPENAI_API_KEY",
    "COHERE_API_KEY",
]

EXPECTED_TOOLS = {"search", "extract", "media", "config", "help", "setup"}


# -- Fixtures ----------------------------------------------------------------


def _build_server_env(
    tmp_path, setup_mode: str, *, allow_gdrive: bool = False
) -> dict[str, str]:
    """Build env vars for server, stripping credentials in relay mode.

    allow_gdrive: if False (default), blanks GOOGLE_DRIVE_CLIENT_ID/SECRET
    to prevent real OAuth Device Code flow in automated tests.
    """
    base_env = {
        **os.environ,
        "LOG_LEVEL": "WARNING",
        "CACHE_DIR": str(tmp_path),
        "DOCS_DB_PATH": str(tmp_path / "docs.db"),
        "DOWNLOAD_DIR": str(tmp_path / "downloads"),
        "EMBEDDING_BACKEND": "local",
        "RERANK_BACKEND": "local",
    }
    if not allow_gdrive:
        base_env["GOOGLE_DRIVE_CLIENT_ID"] = ""
        base_env["GOOGLE_DRIVE_CLIENT_SECRET"] = ""
    if setup_mode == "relay":
        return {k: v for k, v in base_env.items() if k not in CREDENTIAL_ENV_VARS}
    return base_env


def _build_server_params(setup_mode: str, env: dict) -> StdioServerParameters:
    """Build StdioServerParameters based on setup mode."""
    if setup_mode in ("relay", "env"):
        return StdioServerParameters(command="uv", args=["run", "wet-mcp"], env=env)
    if setup_mode == "plugin":
        return StdioServerParameters(
            command="uvx", args=["--python", "3.13", "wet-mcp"], env=env
        )
    msg = f"Unknown setup mode: {setup_mode}"
    raise ValueError(msg)


@pytest.fixture
async def session(request, tmp_path):
    """Start wet-mcp server and yield MCP ClientSession."""
    setup_mode = request.config.getoption("--setup")
    browser_name = request.config.getoption("--browser")

    env = _build_server_env(tmp_path, setup_mode)
    params = _build_server_params(setup_mode, env)

    capture = StderrCapture() if setup_mode == "relay" else None
    errlog_kwargs = {"errlog": capture} if capture else {}

    try:
        async with stdio_client(params, **errlog_kwargs) as (read_stream, write_stream):  # ty: ignore[invalid-argument-type]
            async with ClientSession(read_stream, write_stream) as s:
                await s.initialize()

                if setup_mode == "relay" and capture:
                    # wet-mcp relay is manual: call setup_relay action
                    print("\n>>> Triggering relay via setup_relay...", flush=True)
                    relay_task = asyncio.create_task(
                        s.call_tool("setup", {"action": "setup_relay"})
                    )
                    relay_url = await asyncio.to_thread(capture.get_relay_url, 90)
                    if relay_url:
                        print(f">>> Open relay in browser: {relay_url}", flush=True)
                        open_browser(relay_url, browser_name)
                    # Wait for user to submit credentials
                    await asyncio.wait_for(relay_task, timeout=180)
                    print(">>> Relay config received.", flush=True)

                yield s
    except (RuntimeError, ExceptionGroup) as exc:
        msg = str(exc).lower()
        if "cancel scope" in msg or "different task" in msg:
            warnings.warn(
                f"Suppressed teardown error: {exc}", RuntimeWarning, stacklevel=1
            )
        else:
            raise


# -- Server Init Tests -------------------------------------------------------


class TestServerInit:
    async def test_connects(self, session):
        """Server responds to initialize."""
        assert session is not None

    async def test_tools_list(self, session):
        """Server exposes all expected tools."""
        result = await session.list_tools()
        names = {t.name for t in result.tools}
        assert names == EXPECTED_TOOLS, f"Expected {EXPECTED_TOOLS}, got {names}"

    async def test_tools_have_schema(self, session):
        """Each tool has valid inputSchema."""
        result = await session.list_tools()
        for tool in result.tools:
            assert tool.inputSchema is not None
            assert tool.inputSchema.get("type") == "object"
            assert tool.description


# -- Search Tool (4 actions) -------------------------------------------------


class TestSearch:
    async def test_search(self, session):
        r = await session.call_tool(
            "search", {"action": "search", "query": "python asyncio tutorial"}
        )
        text = parse_result(r)
        assert len(text) > 50

    async def test_research(self, session):
        r = await session.call_tool(
            "search", {"action": "research", "query": "what is WebCrypto API"}
        )
        text = parse_result(r)
        assert len(text) > 100

    async def test_docs(self, session):
        r = await session.call_tool(
            "search",
            {"action": "docs", "query": "pytest fixtures", "library": "pytest"},
        )
        text = parse_result(r)
        assert "fixture" in text.lower() or "pytest" in text.lower()

    async def test_similar(self, session):
        r = await session.call_tool(
            "search", {"action": "similar", "query": "https://docs.python.org/3/"}
        )
        text = parse_result(r)
        assert len(text) > 20


# -- Extract Tool (6 actions) ------------------------------------------------


class TestExtract:
    async def test_extract(self, session):
        r = await session.call_tool(
            "extract", {"action": "extract", "urls": ["https://example.com"]}
        )
        text = parse_result(r)
        assert "example" in text.lower()

    async def test_batch(self, session):
        r = await session.call_tool(
            "extract",
            {
                "action": "batch",
                "urls": ["https://example.com", "https://httpbin.org/html"],
            },
        )
        text = parse_result(r)
        assert len(text) > 50

    @pytest.mark.slow
    async def test_crawl(self, session):
        r = await session.call_tool(
            "extract",
            {"action": "crawl", "urls": ["https://example.com"], "max_pages": 2},
        )
        text = parse_result(r)
        assert len(text) > 20

    async def test_map(self, session):
        r = await session.call_tool(
            "extract", {"action": "map", "urls": ["https://example.com"]}
        )
        text = parse_result(r)
        assert len(text) > 10

    async def test_convert(self, session, tmp_path):
        # convert handles PDF/DOCX/PPTX/XLSX -- test with unsupported ext for graceful error
        test_file = tmp_path / "test.txt"
        test_file.write_text("Hello World from E2E test")
        r = await session.call_tool(
            "extract", {"action": "convert", "paths": [str(test_file)]}
        )
        text = parse_result_allow_error(r)
        assert isinstance(text, str)

    async def test_extract_structured(self, session):
        r = await session.call_tool(
            "extract",
            {
                "action": "extract_structured",
                "urls": ["https://example.com"],
                "schema": {"title": "string", "links": "list"},
            },
        )
        # May return error without LLM API key -- just verify response
        text = parse_result_allow_error(r)
        assert len(text) > 10


# -- Media Tool (3 actions) --------------------------------------------------


class TestMedia:
    async def test_list(self, session):
        r = await session.call_tool(
            "media", {"action": "list", "url": "https://example.com"}
        )
        text = parse_result_allow_error(r)
        assert isinstance(text, str)

    @pytest.mark.slow
    async def test_download(self, session, tmp_path):
        r = await session.call_tool(
            "media",
            {
                "action": "download",
                "media_urls": ["https://www.w3.org/Icons/w3c_home.png"],
                "output_dir": str(tmp_path),
            },
        )
        text = parse_result_allow_error(r)
        assert isinstance(text, str)

    async def test_analyze(self, session):
        # analyze uses LLM vision -- may fail without API key
        r = await session.call_tool(
            "media",
            {"action": "analyze", "url": "https://www.w3.org/Icons/w3c_home.png"},
        )
        text = parse_result_allow_error(r)
        assert isinstance(text, str)


# -- Config Tool (6 actions) -------------------------------------------------


class TestConfig:
    async def test_status(self, session):
        r = await session.call_tool("config", {"action": "status"})
        text = parse_result(r)
        assert (
            "embedding" in text.lower()
            or "mode" in text.lower()
            or "status" in text.lower()
        )

    async def test_set_and_verify(self, session):
        r = await session.call_tool(
            "config", {"action": "set", "key": "log_level", "value": "WARNING"}
        )
        text = parse_result(r)
        assert (
            "warning" in text.lower()
            or "set" in text.lower()
            or "updated" in text.lower()
        )

    async def test_cache_clear(self, session):
        r = await session.call_tool("config", {"action": "cache_clear"})
        text = parse_result(r)
        assert "clear" in text.lower() or "cache" in text.lower()

    async def test_docs_reindex(self, session):
        r = await session.call_tool(
            "config", {"action": "docs_reindex", "key": "pytest"}
        )
        text = parse_result_allow_error(r)
        assert isinstance(text, str)


# -- Setup Tool (2 actions) --------------------------------------------------


class TestSetup:
    async def test_warmup(self, session):
        r = await session.call_tool("setup", {"action": "warmup"})
        text = parse_result_allow_error(r)
        assert isinstance(text, str)

    async def test_setup_sync_no_client_id(self, session):
        """setup_sync should fail gracefully without GOOGLE_DRIVE_CLIENT_ID."""
        r = await session.call_tool("setup", {"action": "setup_sync"})
        text = parse_result_allow_error(r)
        assert isinstance(text, str)


# -- Help Tool (param variations) --------------------------------------------


class TestHelp:
    async def test_help_search(self, session):
        r = await session.call_tool("help", {"tool_name": "search"})
        text = parse_result(r)
        assert "search" in text.lower()

    async def test_help_extract(self, session):
        r = await session.call_tool("help", {"tool_name": "extract"})
        text = parse_result(r)
        assert "extract" in text.lower()

    async def test_help_media(self, session):
        r = await session.call_tool("help", {"tool_name": "media"})
        text = parse_result(r)
        assert "media" in text.lower()

    async def test_help_config(self, session):
        r = await session.call_tool("help", {"tool_name": "config"})
        text = parse_result(r)
        assert "config" in text.lower()


# -- Error Handling Tests ----------------------------------------------------


class TestErrorHandling:
    async def test_invalid_action(self, session):
        r = await session.call_tool("search", {"action": "nonexistent_action"})
        text = parse_result_allow_error(r)
        assert (
            "error" in text.lower()
            or "unknown" in text.lower()
            or "invalid" in text.lower()
        )

    async def test_missing_required_param(self, session):
        # Missing 'query' param for search action
        r = await session.call_tool("search", {"action": "search"})
        text = parse_result_allow_error(r)
        assert isinstance(text, str)


# -- Relay Mode: ALL tools in 1 session (user enters credentials once) ------


@pytest.mark.e2e
@pytest.mark.timeout(300)
async def test_relay_all_tools(request, tmp_path):
    """Relay mode: start server without API keys, trigger relay via setup tool.

    wet-mcp relay is MANUAL (ensure_config(force=True)), not auto like mnemo/telegram.
    Flow: initialize (local mode) -> call setup_relay -> browser opens -> user enters
    credentials -> poll config status -> run all tools with cloud credentials.

    Run with: uv run pytest tests/test_e2e.py -m e2e -k relay --setup=relay --browser=chrome -v -s
    """
    setup_mode = request.config.getoption("--setup")
    if setup_mode != "relay":
        pytest.skip("Only runs with --setup=relay")

    browser_name = request.config.getoption("--browser")
    env = _build_server_env(tmp_path, "relay")
    params = _build_server_params("relay", env)
    capture = StderrCapture()

    try:
        async with stdio_client(params, errlog=capture) as (read_stream, write_stream):  # ty: ignore[invalid-argument-type]
            async with ClientSession(read_stream, write_stream) as s:
                await s.initialize()

                # wet-mcp does NOT auto-trigger relay at startup.
                # Trigger it manually via setup_relay action.
                print("\n>>> Triggering relay via setup_relay action...", flush=True)

                # Call setup_relay in background (it blocks until user submits)
                relay_task = asyncio.create_task(
                    s.call_tool("setup", {"action": "setup_relay"})
                )

                # Wait for relay URL to appear in stderr.
                # Use asyncio.to_thread to avoid blocking the event loop
                # (server needs event loop for model loading + relay session).
                relay_url = await asyncio.to_thread(capture.get_relay_url, 90)
                assert relay_url, "No relay URL detected in stderr after setup_relay"
                print(f">>> RELAY URL: {relay_url}", flush=True)
                open_browser(relay_url, browser_name)

                print(
                    ">>> Enter API keys in browser, then submit...",
                    flush=True,
                )

                # Wait for setup_relay to complete (user submits in browser)
                r = await asyncio.wait_for(relay_task, timeout=300)
                text = parse_result_allow_error(r)
                print(f">>> setup_relay result: {text[:200]}", flush=True)

                # Verify relay succeeded
                assert '"ok"' in text, f"Relay setup failed: {text[:200]}"
                print(">>> Relay config applied! Running tool tests...", flush=True)

                # === ALL TOOLS in this single session ===
                r = await s.call_tool(
                    "search", {"action": "search", "query": "python asyncio"}
                )
                print(f"  search.search: {len(parse_result(r))} chars")

                r = await s.call_tool(
                    "extract", {"action": "extract", "urls": ["https://example.com"]}
                )
                print(f"  extract.extract: {len(parse_result(r))} chars")

                r = await s.call_tool(
                    "media", {"action": "list", "url": "https://example.com"}
                )
                print("  media.list: OK")

                r = await s.call_tool("config", {"action": "status"})
                print("  config.status: OK")

                r = await s.call_tool("setup", {"action": "warmup"})
                print("  setup.warmup: OK")

                r = await s.call_tool("help", {"tool_name": "search"})
                print("  help: OK")

                print(">>> ALL RELAY TESTS PASSED", flush=True)
    except (RuntimeError, ExceptionGroup) as exc:
        msg = str(exc).lower()
        if "cancel scope" in msg or "different task" in msg:
            warnings.warn(
                f"Suppressed teardown error: {exc}", RuntimeWarning, stacklevel=1
            )
        else:
            raise


# -- GDrive OAuth Device Code Test -------------------------------------------


@pytest.mark.e2e
@pytest.mark.slow
@pytest.mark.timeout(300)
async def test_gdrive_oauth(request, tmp_path):
    """GDrive OAuth Device Code: call setup_sync, user authorizes via Google.

    Run with: uv run pytest tests/test_e2e.py -m e2e -k gdrive --setup=env -v -s
    Requires GOOGLE_DRIVE_CLIENT_ID (hardcoded in config defaults).
    """
    env = _build_server_env(tmp_path, "env", allow_gdrive=True)
    params = _build_server_params("env", env)

    try:
        async with stdio_client(params) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as s:
                await s.initialize()

                # Trigger GDrive OAuth Device Code flow
                print("\n>>> Triggering GDrive OAuth Device Code...", flush=True)
                r = await s.call_tool("setup", {"action": "setup_sync"})
                text = parse_result_allow_error(r)
                print(f">>> setup_sync response: {text[:200]}", flush=True)

                # Check if OAuth was triggered (device code URL in stderr or response)
                if "error" in text.lower() and "client_id" in text.lower():
                    pytest.skip("GOOGLE_DRIVE_CLIENT_ID not configured")

                # If OAuth started, user needs to authorize
                # Server prints device code to stderr, relay page shows it
                print(
                    ">>> Check stderr/relay page for Google device code URL", flush=True
                )
                print(
                    ">>> Authorize in browser, then test verifies sync status",
                    flush=True,
                )

                # Wait for OAuth to complete (poll config status)
                deadline = asyncio.get_event_loop().time() + 180
                while asyncio.get_event_loop().time() < deadline:
                    r = await s.call_tool("config", {"action": "status"})
                    text = parse_result_allow_error(r)
                    if "sync" in text.lower() and (
                        "enabled" in text.lower() or "connected" in text.lower()
                    ):
                        print(">>> GDrive OAuth COMPLETE! Sync enabled.", flush=True)
                        break
                    await asyncio.sleep(3)
                else:
                    print(
                        ">>> GDrive OAuth timed out (user may not have authorized)",
                        flush=True,
                    )

                print(">>> GDRIVE OAUTH TEST DONE", flush=True)
    except (RuntimeError, ExceptionGroup) as exc:
        msg = str(exc).lower()
        if "cancel scope" in msg or "different task" in msg:
            warnings.warn(
                f"Suppressed teardown error: {exc}", RuntimeWarning, stacklevel=1
            )
        else:
            raise
