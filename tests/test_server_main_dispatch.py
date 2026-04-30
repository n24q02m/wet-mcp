"""Tests for wet_mcp.server main() entry point + run_http() modes.

Covers MCP_MODE dispatch branches and the multi-user remote mode wired in
2026-04-26 (PUBLIC_URL switch + per-sub credential storage). The legacy
``run_remote_relay()`` (single-user MCP_RELAY_URL pattern) was deleted in
the same change; ``MCP_MODE=remote-relay`` now raises a deprecation
SystemExit.
"""

import sys
from unittest.mock import AsyncMock, patch

import pytest


class TestRunHttp:
    """run_http() starts local HTTP server via mcp-core run_local_server."""

    async def test_delegates_to_run_local_server(self, monkeypatch):
        monkeypatch.delenv("PUBLIC_URL", raising=False)
        from wet_mcp.server import run_http

        with (
            patch(
                "mcp_core.transport.local_server.run_local_server",
                new_callable=AsyncMock,
            ) as mock_run_local,
        ):
            await run_http(port=0)

            mock_run_local.assert_called_once()
            args, kwargs = mock_run_local.call_args
            assert kwargs["server_name"] == "wet-mcp"
            assert kwargs["port"] == 0
            assert kwargs["host"] == "127.0.0.1"
            assert "relay_schema" in kwargs
            assert "on_credentials_saved" in kwargs

    async def test_custom_port_passed_through(self, monkeypatch):
        monkeypatch.delenv("PUBLIC_URL", raising=False)
        from wet_mcp.server import run_http

        with patch(
            "mcp_core.transport.local_server.run_local_server",
            new_callable=AsyncMock,
        ) as mock_run_local:
            await run_http(port=19999)
            _, kwargs = mock_run_local.call_args
            assert kwargs["port"] == 19999

    async def test_public_url_without_dcr_secret_refuses_start(self, monkeypatch):
        """Multi-user remote mode requires MCP_DCR_SERVER_SECRET."""
        from wet_mcp.server import run_http

        monkeypatch.setenv("PUBLIC_URL", "https://wet.example.com")
        monkeypatch.delenv("MCP_DCR_SERVER_SECRET", raising=False)

        with pytest.raises(SystemExit, match="MCP_DCR_SERVER_SECRET missing"):
            await run_http()

    async def test_public_url_with_dcr_secret_binds_0000_8080(self, monkeypatch):
        """PUBLIC_URL + MCP_DCR_SERVER_SECRET -> 0.0.0.0:8080 multi-user remote."""
        from wet_mcp.server import run_http

        monkeypatch.setenv("PUBLIC_URL", "https://wet.example.com")
        monkeypatch.setenv("MCP_DCR_SERVER_SECRET", "test-dcr-secret")
        monkeypatch.delenv("MCP_PORT", raising=False)

        with patch(
            "mcp_core.transport.local_server.run_local_server",
            new_callable=AsyncMock,
        ) as mock_run_local:
            await run_http()

            _, kwargs = mock_run_local.call_args
            assert kwargs["host"] == "0.0.0.0"
            assert kwargs["port"] == 8080

    async def test_public_url_respects_mcp_port_override(self, monkeypatch):
        """MCP_PORT overrides default 8080 in multi-user remote mode."""
        from wet_mcp.server import run_http

        monkeypatch.setenv("PUBLIC_URL", "https://wet.example.com")
        monkeypatch.setenv("MCP_DCR_SERVER_SECRET", "test-dcr-secret")
        monkeypatch.setenv("MCP_PORT", "9090")

        with patch(
            "mcp_core.transport.local_server.run_local_server",
            new_callable=AsyncMock,
        ) as mock_run_local:
            await run_http()

            _, kwargs = mock_run_local.call_args
            assert kwargs["host"] == "0.0.0.0"
            assert kwargs["port"] == 9090


class TestMainDispatch:
    """main() routes to correct entry point based on MCP_MODE."""

    def test_stdio_flag_runs_mcp(self, monkeypatch):
        """--stdio flag routes main() to FastMCP stdio server directly."""
        from wet_mcp import server
        from wet_mcp.server import main

        monkeypatch.setattr(sys, "argv", ["wet-mcp", "--stdio"])
        monkeypatch.delenv("MCP_MODE", raising=False)
        monkeypatch.delenv("MCP_TRANSPORT", raising=False)

        with patch.object(server.mcp, "run") as mock_run:
            main()
        mock_run.assert_called_once_with(transport="stdio")

    def test_mcp_transport_stdio_runs_mcp(self, monkeypatch):
        """MCP_TRANSPORT=stdio routes main() to FastMCP stdio server directly."""
        from wet_mcp import server
        from wet_mcp.server import main

        monkeypatch.setattr(sys, "argv", ["wet-mcp"])
        monkeypatch.setenv("MCP_TRANSPORT", "stdio")
        monkeypatch.delenv("MCP_MODE", raising=False)

        with patch.object(server.mcp, "run") as mock_run:
            main()
        mock_run.assert_called_once_with(transport="stdio")

    def test_remote_relay_mode_raises_deprecation(self, monkeypatch):
        """MCP_MODE=remote-relay was deprecated 2026-04-26 (single-user pattern)."""
        from wet_mcp.server import main

        monkeypatch.setattr(sys, "argv", ["wet-mcp"])
        monkeypatch.setenv("MCP_MODE", "remote-relay")
        monkeypatch.delenv("MCP_TRANSPORT", raising=False)

        with pytest.raises(SystemExit, match="deprecated"):
            main()

    def test_local_relay_mode_runs_http(self, monkeypatch):
        from wet_mcp.server import main

        monkeypatch.setattr(sys, "argv", ["wet-mcp"])
        monkeypatch.setenv("MCP_MODE", "local-relay")
        monkeypatch.delenv("MCP_TRANSPORT", raising=False)

        with (
            patch("wet_mcp.server.asyncio.run") as mock_run,
            patch("wet_mcp.server.run_http") as mock_http,
        ):
            main()
            mock_run.assert_called_once()
            mock_http.assert_called_once()

    def test_no_mode_defaults_to_http(self, monkeypatch):
        from wet_mcp.server import main

        monkeypatch.setattr(sys, "argv", ["wet-mcp"])
        monkeypatch.delenv("MCP_MODE", raising=False)
        monkeypatch.delenv("MCP_TRANSPORT", raising=False)

        with (
            patch("wet_mcp.server.asyncio.run") as mock_run,
            patch("wet_mcp.server.run_http") as mock_http,
        ):
            main()
            mock_run.assert_called_once()
            mock_http.assert_called_once()

    def test_unsupported_mode_raises_systemexit(self, monkeypatch):
        from wet_mcp.server import main

        monkeypatch.setattr(sys, "argv", ["wet-mcp"])
        monkeypatch.setenv("MCP_MODE", "nonsense")
        monkeypatch.delenv("MCP_TRANSPORT", raising=False)

        with pytest.raises(SystemExit, match="Unsupported MCP_MODE"):
            main()
