"""WET MCP Server - Web Extended Toolkit for AI Agents."""

from importlib.metadata import PackageNotFoundError, version

from wet_mcp.__main__ import _cli as main
from wet_mcp.server import mcp

try:
    __version__ = version("wet-mcp")
except PackageNotFoundError:
    __version__ = "0.0.0-dev"

__all__ = ["mcp", "main", "__version__"]
