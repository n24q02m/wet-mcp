"""WET MCP Server entry point."""

from wet_mcp.server import main


def _cli() -> None:
    import sys
    if sys.platform == "win32":
        import io
        for _s in (sys.stdout, sys.stderr):
            if _s is not None:
                try:
                    _s.reconfigure(encoding="utf-8", errors="replace")
                except (AttributeError, io.UnsupportedOperation):
                    pass

    """Start the MCP server."""
    main()


if __name__ == "__main__":  # pragma: no cover
    _cli()
