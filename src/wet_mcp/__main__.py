"""WET MCP Server entry point."""

from wet_mcp.server import main


def _cli() -> None:
    """Start the MCP server."""
    main()


if __name__ == "__main__":
    _cli()
