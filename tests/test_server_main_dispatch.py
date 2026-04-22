"""Tests for wet_mcp.server main() entry point + run_remote_relay().

Covers MCP_MODE dispatch branches and the remote-relay setup wired in
2026-04-22 (matrix correction for self-host semantics).
"""

import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestRunRemoteRelay:
    """run_remote_relay() drives ensure_config and starts Streamable HTTP."""

    @pytest.fixture(autouse=True)
    def _relay_url(self, monkeypatch):
        """Remote-relay mode requires explicit MCP_RELAY_URL per matrix 2.5."""
        monkeypatch.setenv("MCP_RELAY_URL", "https://relay.example.com")

    async def test_ensure_config_applied_when_available(self, monkeypatch):
        """Happy path: ensure_config returns creds, apply_config called, server starts."""
        from wet_mcp.server import run_remote_relay

        mock_config = {"GEMINI_API_KEY": "from-relay"}

        with (
            patch(
                "wet_mcp.relay_setup.ensure_config", new_callable=AsyncMock
            ) as mock_ec,
            patch("wet_mcp.relay_setup.apply_config") as mock_apply,
            patch("wet_mcp.server.mcp") as mock_mcp,
        ):
            mock_ec.return_value = mock_config
            mock_mcp.run_streamable_http_async = AsyncMock()
            mock_mcp.settings = MagicMock()

            await run_remote_relay()

            mock_ec.assert_called_once()
            mock_apply.assert_called_once_with(mock_config)
            mock_mcp.run_streamable_http_async.assert_called_once()

    async def test_warns_when_relay_produces_no_creds(self, monkeypatch):
        """When ensure_config returns None, logs warning but still starts server."""
        from wet_mcp.server import run_remote_relay

        with (
            patch(
                "wet_mcp.relay_setup.ensure_config", new_callable=AsyncMock
            ) as mock_ec,
            patch("wet_mcp.relay_setup.apply_config") as mock_apply,
            patch("wet_mcp.server.mcp") as mock_mcp,
        ):
            mock_ec.return_value = None
            mock_mcp.run_streamable_http_async = AsyncMock()
            mock_mcp.settings = MagicMock()

            await run_remote_relay()

            mock_apply.assert_not_called()
            mock_mcp.run_streamable_http_async.assert_called_once()

    async def test_reads_mcp_host_port_env_vars(self, monkeypatch):
        """MCP_HOST and MCP_PORT env vars override defaults."""
        from wet_mcp.server import run_remote_relay

        monkeypatch.setenv("MCP_HOST", "0.0.0.0")
        monkeypatch.setenv("MCP_PORT", "18080")

        with (
            patch(
                "wet_mcp.relay_setup.ensure_config", new_callable=AsyncMock
            ) as mock_ec,
            patch("wet_mcp.server.mcp") as mock_mcp,
        ):
            mock_ec.return_value = None
            mock_mcp.run_streamable_http_async = AsyncMock()
            mock_mcp.settings = MagicMock()

            await run_remote_relay()

            assert mock_mcp.settings.host == "0.0.0.0"
            assert mock_mcp.settings.port == 18080

    async def test_invalid_port_falls_back_to_zero(self, monkeypatch):
        """Non-numeric MCP_PORT uses auto-port (0)."""
        from wet_mcp.server import run_remote_relay

        monkeypatch.setenv("MCP_PORT", "not-a-number")

        with (
            patch(
                "wet_mcp.relay_setup.ensure_config", new_callable=AsyncMock
            ) as mock_ec,
            patch("wet_mcp.server.mcp") as mock_mcp,
        ):
            mock_ec.return_value = None
            mock_mcp.run_streamable_http_async = AsyncMock()
            mock_mcp.settings = MagicMock()

            await run_remote_relay()

            assert mock_mcp.settings.port == 0

    async def test_invalid_timeout_falls_back_to_300(self, monkeypatch):
        """Non-numeric MCP_RELAY_TIMEOUT_S uses default 300s."""
        from wet_mcp.server import run_remote_relay

        monkeypatch.setenv("MCP_RELAY_TIMEOUT_S", "not-a-number")

        with (
            patch(
                "wet_mcp.relay_setup.ensure_config", new_callable=AsyncMock
            ) as mock_ec,
            patch("wet_mcp.server.mcp") as mock_mcp,
        ):
            mock_ec.return_value = None
            mock_mcp.run_streamable_http_async = AsyncMock()
            mock_mcp.settings = MagicMock()

            await run_remote_relay()

            _, kwargs = mock_ec.call_args
            assert kwargs["timeout"] == 300.0


class TestRunHttp:
    """run_http() starts local HTTP server via mcp-core run_local_server."""

    async def test_delegates_to_run_local_server(self):
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
            assert "relay_schema" in kwargs
            assert "on_credentials_saved" in kwargs

    async def test_custom_port_passed_through(self):
        from wet_mcp.server import run_http

        with patch(
            "mcp_core.transport.local_server.run_local_server",
            new_callable=AsyncMock,
        ) as mock_run_local:
            await run_http(port=19999)
            _, kwargs = mock_run_local.call_args
            assert kwargs["port"] == 19999


class TestMainDispatch:
    """main() routes to correct entry point based on MCP_MODE."""

    def test_stdio_flag_runs_mcp(self, monkeypatch):
        from wet_mcp.server import main

        monkeypatch.setattr(sys, "argv", ["wet-mcp", "--stdio"])
        monkeypatch.delenv("MCP_MODE", raising=False)
        monkeypatch.delenv("MCP_TRANSPORT", raising=False)

        with patch("wet_mcp.server.mcp") as mock_mcp:
            main()
            mock_mcp.run.assert_called_once()

    def test_mcp_transport_stdio_runs_mcp(self, monkeypatch):
        from wet_mcp.server import main

        monkeypatch.setattr(sys, "argv", ["wet-mcp"])
        monkeypatch.setenv("MCP_TRANSPORT", "stdio")
        monkeypatch.delenv("MCP_MODE", raising=False)

        with patch("wet_mcp.server.mcp") as mock_mcp:
            main()
            mock_mcp.run.assert_called_once()

    def test_remote_relay_mode_runs_remote_relay(self, monkeypatch):
        from wet_mcp.server import main

        monkeypatch.setattr(sys, "argv", ["wet-mcp"])
        monkeypatch.setenv("MCP_MODE", "remote-relay")
        monkeypatch.delenv("MCP_TRANSPORT", raising=False)

        with (
            patch("wet_mcp.server.asyncio.run") as mock_run,
            patch("wet_mcp.server.run_remote_relay") as mock_remote,
        ):
            main()
            mock_run.assert_called_once()
            mock_remote.assert_called_once()

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
