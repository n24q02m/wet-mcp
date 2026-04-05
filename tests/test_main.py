"""Tests for wet_mcp.__main__ — CLI entry point and setup_tool functions."""

import sys
from unittest.mock import MagicMock, patch

import numpy as np


class TestCli:
    """CLI dispatcher starts MCP server."""

    @patch("wet_mcp.__main__.main")
    def test_default_runs_server(self, mock_main):
        from wet_mcp.__main__ import _cli

        _cli()
        mock_main.assert_called_once()

    @patch("wet_mcp.__main__.main")
    def test_cli_always_runs_server(self, mock_main):
        """_cli() always starts MCP server (no subcommands)."""
        from wet_mcp.__main__ import _cli

        with patch.object(sys, "argv", ["wet-mcp", "anything"]):
            _cli()
        mock_main.assert_called_once()


