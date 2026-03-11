import asyncio
from unittest.mock import MagicMock, patch, AsyncMock
from contextlib import asynccontextmanager

import pytest
import warnings

async def run_test():
    from wet_mcp import server
    mock_fastmcp = MagicMock()
    with (
        patch("wet_mcp.server.WebCache"),
        patch("wet_mcp.server.DocsDB"),
        patch("wet_mcp.server.shutdown_crawler", new_callable=AsyncMock),
        patch("wet_mcp.server.stop_searxng"),
        patch(
            "wet_mcp.server._init_embedding_backend",
            new_callable=AsyncMock,
            side_effect=Exception("backend init error"),
        ),
    ):
        async with server._lifespan(mock_fastmcp):
            # Allow background tasks to run
            await asyncio.sleep(0.1)

asyncio.run(run_test())
