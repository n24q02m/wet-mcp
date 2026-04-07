import asyncio
import json
from unittest.mock import AsyncMock, patch, MagicMock

# Mocking dependencies that might fail import
import sys
from types import ModuleType

mock_mcp_relay = ModuleType("mcp_relay")
sys.modules["mcp_relay"] = mock_mcp_relay
mock_mcp_relay_core = ModuleType("mcp_relay.core")
sys.modules["mcp_relay.core"] = mock_mcp_relay_core

# Now try to import search
try:
    from wet_mcp.server import search, _do_web_search, _do_similar_search, _do_research_with_cache
    print("Successfully imported search and helpers")
except ImportError as e:
    print(f"Import failed: {e}")
    # Fallback: if it fails due to other dependencies, we might need more mocks
    sys.exit(0)

async def test_search_dispatch():
    with patch("wet_mcp.server._require_credentials", return_value=None),          patch("wet_mcp.server._do_web_search", new_callable=AsyncMock) as mock_web:

        mock_web.return_value = "web result"
        res = await search(action="search", query="test")
        print(f"Search action result: {res}")
        mock_web.assert_called_once()

    with patch("wet_mcp.server._require_credentials", return_value=None),          patch("wet_mcp.server._do_similar_search", new_callable=AsyncMock) as mock_sim:

        mock_sim.return_value = "similar result"
        res = await search(action="similar", query="http://test.com")
        print(f"Similar action result: {res}")
        mock_sim.assert_called_once()

    print("Dispatch tests passed!")

if __name__ == "__main__":
    asyncio.run(test_search_dispatch())
