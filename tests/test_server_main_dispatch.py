"""Tests for wet_mcp.server main() entry point + run_http_server() modes.

Covers the stdio-pure / HTTP-multi-user dispatch wired in spec
``2026-05-01-stdio-pure-http-multiuser.md``: stdio is the default,
``--http`` (or ``MCP_TRANSPORT=http`` / ``TRANSPORT_MODE=http``) opts
into the HTTP server. The legacy ``MCP_MODE`` env var (and
``remote-relay`` deprecation branch) were deleted in the same change.
"""

import sys
from unittest.mock import AsyncMock, patch

import pytest


class TestRunHttpServer:
    """run_http_server() starts HTTP server via mcp-core run_http_server."""

    async def test_delegates_to_run_http_server(self, monkeypatch):
        monkeypatch.delenv("PUBLIC_URL", raising=False)
        from wet_mcp.server import run_http_server

        with (
            patch(
                "mcp_core.transport.local_server.run_http_server",
                new_callable=AsyncMock,
            ) as mock_run_http,
        ):
            await run_http_server(port=0)

            mock_run_http.assert_called_once()
            args, kwargs = mock_run_http.call_args
            assert kwargs["server_name"] == "wet-mcp"
            assert kwargs["port"] == 0
            assert kwargs["host"] == "127.0.0.1"
            assert "relay_schema" in kwargs
            assert "on_credentials_saved" in kwargs

    async def test_custom_port_passed_through(self, monkeypatch):
        monkeypatch.delenv("PUBLIC_URL", raising=False)
        from wet_mcp.server import run_http_server

        with patch(
            "mcp_core.transport.local_server.run_http_server",
            new_callable=AsyncMock,
        ) as mock_run_http:
            await run_http_server(port=19999)
            _, kwargs = mock_run_http.call_args
            assert kwargs["port"] == 19999

    async def test_public_url_without_dcr_secret_refuses_start(self, monkeypatch):
        """Multi-user remote mode requires MCP_DCR_SERVER_SECRET."""
        from wet_mcp.server import run_http_server

        monkeypatch.setenv("PUBLIC_URL", "https://wet.example.com")
        monkeypatch.delenv("MCP_DCR_SERVER_SECRET", raising=False)

        with pytest.raises(SystemExit, match="MCP_DCR_SERVER_SECRET missing"):
            await run_http_server()

    async def test_public_url_with_dcr_secret_binds_0000_8080(self, monkeypatch):
        """PUBLIC_URL + MCP_DCR_SERVER_SECRET -> 0.0.0.0:8080 multi-user remote."""
        from wet_mcp.server import run_http_server

        monkeypatch.setenv("PUBLIC_URL", "https://wet.example.com")
        monkeypatch.setenv("MCP_DCR_SERVER_SECRET", "test-dcr-secret")
        monkeypatch.delenv("MCP_PORT", raising=False)

        with patch(
            "mcp_core.transport.local_server.run_http_server",
            new_callable=AsyncMock,
        ) as mock_run_http:
            await run_http_server()

            _, kwargs = mock_run_http.call_args
            assert kwargs["host"] == "0.0.0.0"
            assert kwargs["port"] == 8080

    async def test_public_url_respects_mcp_port_override(self, monkeypatch):
        """MCP_PORT overrides default 8080 in multi-user remote mode."""
        from wet_mcp.server import run_http_server

        monkeypatch.setenv("PUBLIC_URL", "https://wet.example.com")
        monkeypatch.setenv("MCP_DCR_SERVER_SECRET", "test-dcr-secret")
        monkeypatch.setenv("MCP_PORT", "9090")

        with patch(
            "mcp_core.transport.local_server.run_http_server",
            new_callable=AsyncMock,
        ) as mock_run_http:
            await run_http_server()

            _, kwargs = mock_run_http.call_args
            assert kwargs["host"] == "0.0.0.0"
            assert kwargs["port"] == 9090


class TestMainDispatch:
    """main() defaults to stdio; ``--http`` / env opts into HTTP."""

    def test_no_args_defaults_to_stdio(self, monkeypatch):
        """Bare ``wet-mcp`` invocation runs FastMCP stdio (new default)."""
        from wet_mcp import server
        from wet_mcp.server import main

        monkeypatch.setattr(sys, "argv", ["wet-mcp"])
        monkeypatch.delenv("MCP_TRANSPORT", raising=False)
        monkeypatch.delenv("TRANSPORT_MODE", raising=False)

        with patch.object(server.mcp, "run") as mock_run:
            main()
        mock_run.assert_called_once_with(transport="stdio")

    def test_stdio_flag_runs_mcp(self, monkeypatch):
        """``--stdio`` is accepted (stdio is also the default)."""
        from wet_mcp import server
        from wet_mcp.server import main

        monkeypatch.setattr(sys, "argv", ["wet-mcp", "--stdio"])
        monkeypatch.delenv("MCP_TRANSPORT", raising=False)
        monkeypatch.delenv("TRANSPORT_MODE", raising=False)

        with patch.object(server.mcp, "run") as mock_run:
            main()
        mock_run.assert_called_once_with(transport="stdio")

    def test_mcp_transport_stdio_runs_mcp(self, monkeypatch):
        """MCP_TRANSPORT=stdio is accepted (stdio is also the default)."""
        from wet_mcp import server
        from wet_mcp.server import main

        monkeypatch.setattr(sys, "argv", ["wet-mcp"])
        monkeypatch.setenv("MCP_TRANSPORT", "stdio")
        monkeypatch.delenv("TRANSPORT_MODE", raising=False)

        with patch.object(server.mcp, "run") as mock_run:
            main()
        mock_run.assert_called_once_with(transport="stdio")

    def test_http_flag_runs_http_server(self, monkeypatch):
        """``--http`` opts into HTTP server."""
        from wet_mcp.server import main

        monkeypatch.setattr(sys, "argv", ["wet-mcp", "--http"])
        monkeypatch.delenv("MCP_TRANSPORT", raising=False)
        monkeypatch.delenv("TRANSPORT_MODE", raising=False)

        with (
            patch("wet_mcp.server.asyncio.run") as mock_run,
            patch("wet_mcp.server.run_http_server") as mock_http,
        ):
            main()
            mock_run.assert_called_once()
            mock_http.assert_called_once()

    def test_mcp_transport_http_runs_http_server(self, monkeypatch):
        """MCP_TRANSPORT=http opts into HTTP server."""
        from wet_mcp.server import main

        monkeypatch.setattr(sys, "argv", ["wet-mcp"])
        monkeypatch.setenv("MCP_TRANSPORT", "http")
        monkeypatch.delenv("TRANSPORT_MODE", raising=False)

        with (
            patch("wet_mcp.server.asyncio.run") as mock_run,
            patch("wet_mcp.server.run_http_server") as mock_http,
        ):
            main()
            mock_run.assert_called_once()
            mock_http.assert_called_once()

    def test_transport_mode_http_runs_http_server(self, monkeypatch):
        """TRANSPORT_MODE=http opts into HTTP server."""
        from wet_mcp.server import main

        monkeypatch.setattr(sys, "argv", ["wet-mcp"])
        monkeypatch.delenv("MCP_TRANSPORT", raising=False)
        monkeypatch.setenv("TRANSPORT_MODE", "http")

        with (
            patch("wet_mcp.server.asyncio.run") as mock_run,
            patch("wet_mcp.server.run_http_server") as mock_http,
        ):
            main()
            mock_run.assert_called_once()
            mock_http.assert_called_once()

    def test_mcp_mode_env_is_ignored(self, monkeypatch):
        """Legacy ``MCP_MODE`` (incl. ``remote-relay``) is no longer read.

        Setting it must NOT raise SystemExit and must NOT route to HTTP --
        the binary still defaults to stdio. Old deprecation branch removed.
        """
        from wet_mcp import server
        from wet_mcp.server import main

        monkeypatch.setattr(sys, "argv", ["wet-mcp"])
        monkeypatch.setenv("MCP_MODE", "remote-relay")
        monkeypatch.delenv("MCP_TRANSPORT", raising=False)
        monkeypatch.delenv("TRANSPORT_MODE", raising=False)

        with patch.object(server.mcp, "run") as mock_run:
            main()
        mock_run.assert_called_once_with(transport="stdio")
