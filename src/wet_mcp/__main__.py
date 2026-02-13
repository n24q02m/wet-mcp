"""WET MCP Server entry point."""

import sys


def _cli() -> None:
    """CLI dispatcher: server (default) or setup-sync subcommand."""
    if len(sys.argv) >= 2 and sys.argv[1] == "setup-sync":
        from wet_mcp.sync import setup_sync

        remote_type = sys.argv[2] if len(sys.argv) >= 3 else "drive"
        setup_sync(remote_type)
    else:
        from wet_mcp.server import main

        main()


if __name__ == "__main__":
    _cli()
