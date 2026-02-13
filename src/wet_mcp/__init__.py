"""WET MCP Server - Web Extended Toolkit for AI Agents."""

from importlib.metadata import version

from wet_mcp.__main__ import _cli as main
from wet_mcp.server import mcp

__version__ = version("wet-mcp")
__all__ = ["mcp", "main", "__version__"]
