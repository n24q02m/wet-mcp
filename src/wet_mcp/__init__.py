"""WET MCP Server - Web ExTract for AI Agents."""

from importlib.metadata import version

from wet_mcp.server import main, mcp

__version__ = version("wet-mcp")
__all__ = ["mcp", "main", "__version__"]
