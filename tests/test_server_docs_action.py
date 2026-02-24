"""Tests for docs action in src/wet_mcp/server.py."""

from unittest.mock import AsyncMock, patch
import pytest

from wet_mcp.server import search

@pytest.mark.asyncio
async def test_docs_success():
    """Test docs action success path."""
    with patch("wet_mcp.server._do_docs_search", new_callable=AsyncMock) as mock_docs_search:
        mock_docs_search.return_value = "Docs Search Results"

        result = await search(
            action="docs",
            library="test-lib",
            query="test query",
            language="python",
            version="1.0",
            limit=5
        )

        assert result == "Docs Search Results"
        mock_docs_search.assert_called_once_with(
            library="test-lib",
            query="test query",
            language="python",
            version="1.0",
            limit=5,
        )

@pytest.mark.asyncio
async def test_docs_missing_library():
    """Test docs action missing library."""
    result = await search(action="docs", query="test query")
    assert "Error: library is required" in result

@pytest.mark.asyncio
async def test_docs_missing_query():
    """Test docs action missing query."""
    result = await search(action="docs", library="test-lib")
    assert "Error: query is required" in result
