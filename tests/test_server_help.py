"""Tests for the help tool in src/wet_mcp/server.py."""

from unittest.mock import MagicMock, patch

import pytest

from wet_mcp.server import help


@pytest.mark.asyncio
async def test_help_success():
    """Test help tool success path."""
    with patch("wet_mcp.server.files") as mock_files:
        mock_path = MagicMock()
        mock_path.read_text.return_value = "# Search Tool\nDocumentation here."
        mock_files.return_value.joinpath.return_value = mock_path

        result = await help(tool_name="search")

        assert result == "# Search Tool\nDocumentation here."
        mock_files.assert_called_once_with("wet_mcp.docs")
        mock_files.return_value.joinpath.assert_called_once_with("search.md")
        mock_path.read_text.assert_called_once()


@pytest.mark.asyncio
async def test_help_default():
    """Test help tool with default argument."""
    with patch("wet_mcp.server.files") as mock_files:
        mock_path = MagicMock()
        mock_path.read_text.return_value = "# Default Tool\nDocs."
        mock_files.return_value.joinpath.return_value = mock_path

        result = await help()

        assert result == "# Default Tool\nDocs."
        mock_files.assert_called_once_with("wet_mcp.docs")
        mock_files.return_value.joinpath.assert_called_once_with("search.md")


@pytest.mark.asyncio
async def test_help_file_not_found():
    """Test help tool when documentation file is not found."""
    with patch("wet_mcp.server.files") as mock_files:
        mock_path = MagicMock()
        mock_path.read_text.side_effect = FileNotFoundError()
        mock_files.return_value.joinpath.return_value = mock_path

        result = await help(tool_name="nonexistent")

        assert result == "Error: No documentation found for tool 'nonexistent'"
        mock_files.assert_called_once_with("wet_mcp.docs")
        mock_files.return_value.joinpath.assert_called_once_with("nonexistent.md")


@pytest.mark.asyncio
async def test_help_generic_exception():
    """Test help tool handles generic exceptions."""
    with patch("wet_mcp.server.files") as mock_files:
        mock_path = MagicMock()
        mock_path.read_text.side_effect = Exception("Disk error")
        mock_files.return_value.joinpath.return_value = mock_path

        result = await help(tool_name="extract")

        assert result == "Error loading documentation: Disk error"
        mock_files.assert_called_once_with("wet_mcp.docs")
        mock_files.return_value.joinpath.assert_called_once_with("extract.md")
