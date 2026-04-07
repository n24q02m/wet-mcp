import asyncio
from unittest.mock import MagicMock, patch
import sys
import os
import pytest

# Add src to sys.path
sys.path.insert(0, os.path.abspath("src"))

# Mock EVERYTHING
mock_names = [
    "loguru", "mcp", "mcp.server", "mcp.server.fastmcp", "mcp.types",
    "crawl4ai", "httpx", "pydantic", "pydantic_settings", "sqlite_vec",
    "wet_mcp.cache", "wet_mcp.db", "wet_mcp.searxng_runner", "wet_mcp.sources",
    "wet_mcp.sources.crawler", "wet_mcp.sources.searxng", "wet_mcp.embedder",
    "wet_mcp.reranker", "wet_mcp.setup", "wet_mcp.sync", "wet_mcp.config",
    "wet_mcp.security", "wet_mcp.credential_state", "importlib.metadata"
]

modules = {name: MagicMock() for name in mock_names}
modules["importlib.metadata"].version.return_value = "0.0.0"

# Mock the settings object specifically
mock_settings = MagicMock()
mock_settings.tool_timeout = 120
modules["wet_mcp.config"].settings = mock_settings

with patch.dict(sys.modules, modules):
    # Now run pytest on the timeout tests
    # We need to ensure the mocks are active during the test run
    pytest.main(["tests/test_server_timeout.py", "-v"])
