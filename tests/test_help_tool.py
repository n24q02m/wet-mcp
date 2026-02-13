"""Tests for the help tool in src/wet_mcp/server.py."""

from unittest.mock import MagicMock, patch

import pytest

from wet_mcp.server import help


@pytest.mark.asyncio
async def test_help_success():
    """Test help tool successfully retrieves documentation."""
    mock_path = MagicMock()
    mock_path.read_text.return_value = "Mock Documentation Content"

    mock_files = MagicMock()
    mock_files.joinpath.return_value = mock_path

    with patch("wet_mcp.server.files", return_value=mock_files) as patched_files:
        result = await help(tool_name="web")

        assert result == "Mock Documentation Content"
        patched_files.assert_called_once_with("wet_mcp.docs")
        mock_files.joinpath.assert_called_once_with("web.md")
        mock_path.read_text.assert_called_once()


@pytest.mark.asyncio
async def test_help_file_not_found():
    """Test help tool when documentation file is missing."""
    mock_path = MagicMock()
    mock_path.read_text.side_effect = FileNotFoundError("File not found")

    mock_files = MagicMock()
    mock_files.joinpath.return_value = mock_path

    with patch("wet_mcp.server.files", return_value=mock_files):
        result = await help(tool_name="non_existent_tool")

        assert "Error: No documentation found" in result
        assert "non_existent_tool" in result


@pytest.mark.asyncio
async def test_help_generic_error():
    """Test help tool when a generic error occurs."""
    mock_path = MagicMock()
    mock_path.read_text.side_effect = Exception("Disk error")

    mock_files = MagicMock()
    mock_files.joinpath.return_value = mock_path

    with patch("wet_mcp.server.files", return_value=mock_files):
        result = await help(tool_name="web")

        assert "Error loading documentation" in result
        assert "Disk error" in result
