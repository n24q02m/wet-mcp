"""Tests for wet_mcp package."""

from wet_mcp import __version__, mcp


def test_version():
    """Test version is set."""
    assert __version__ == "0.1.0"


def test_mcp_server_exists():
    """Test MCP server is initialized."""
    assert mcp is not None
    assert mcp.name == "wet"
