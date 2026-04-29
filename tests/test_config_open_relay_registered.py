"""Smoke test: ``config__open_relay`` MCP tool is registered.

Transparent Bridge v2 (Wave 3) — wet-mcp consumes the
``register_open_relay_tool`` helper from ``mcp-core`` so an LLM can
re-trigger the relay form after the daemon is already running. This test
imports ``wet_mcp.server`` (running module-level registration) and asserts
the tool name appears in the FastMCP tool registry.
"""

from __future__ import annotations


def test_config_open_relay_tool_is_registered() -> None:
    from wet_mcp import server

    names = {tool.name for tool in server.mcp._tool_manager.list_tools()}
    assert "config__open_relay" in names, (
        "register_open_relay_tool() must register `config__open_relay` "
        "into the FastMCP instance at module import time. Registered "
        f"tools were: {sorted(names)}"
    )
