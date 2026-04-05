import time
from unittest.mock import AsyncMock, patch

import pytest

import wet_mcp.searxng_runner as wet_runner


@pytest.mark.asyncio
async def test_health_check_caching():
    # Clear the cache before starting
    wet_runner._health_cache.clear()

    # Patch the original health check
    with patch(
        "wet_mcp.searxng_runner._wc_original_health_check", new_callable=AsyncMock
    ) as mock_original:
        mock_original.return_value = True

        url = "http://localhost:8080"

        # 1. First call - should call original
        res1 = await wet_runner._quick_health_check(url)
        assert res1 is True
        assert mock_original.call_count == 1

        # 2. Second call - should be cached
        res2 = await wet_runner._quick_health_check(url)
        assert res2 is True
        assert mock_original.call_count == 1

        # 3. Third call with different URL - should call original
        url2 = "http://localhost:8081"
        res3 = await wet_runner._quick_health_check(url2)
        assert res3 is True
        assert mock_original.call_count == 2

        # 4. Wait for TTL to expire (10s)
        # Instead of mocking time.time globally which might break other things,
        # we can manually manipulate the cache timestamp
        now = time.time()
        wet_runner._health_cache[url] = (True, now - 11)

        res4 = await wet_runner._quick_health_check(url)
        assert res4 is True
        # It should have called original again because timestamp is old
        assert mock_original.call_count == 3
