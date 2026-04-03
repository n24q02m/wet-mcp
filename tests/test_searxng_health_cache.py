import time
from unittest.mock import MagicMock, patch

import pytest

from wet_mcp.searxng_runner import _health_cache, _quick_health_check


@pytest.mark.asyncio
async def test_quick_health_check_caching():
    # Clear cache before test
    _health_cache.clear()

    url = "http://localhost:8888"

    # Mock httpx.AsyncClient.get
    with patch("httpx.AsyncClient.get") as mock_get:
        # First call - should hit the network
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_get.return_value = mock_response

        result1 = await _quick_health_check(url)
        assert result1 is True
        assert mock_get.call_count == 1

        # Second call - should hit the cache
        result2 = await _quick_health_check(url)
        assert result2 is True
        assert mock_get.call_count == 1

        # Third call with different URL - should hit the network
        url2 = "http://localhost:9999"
        result3 = await _quick_health_check(url2)
        assert result3 is True
        assert mock_get.call_count == 2

        # Fourth call - wait for TTL to expire
        # Use a real timestamp then patch time.time to return it as a value, not a mock
        now = time.time()
        with patch("time.time", side_effect=[now, now + 11.0]):
            # This should be a cache miss because the timestamp in cache is from first call,
            # and now is still 'now' (or roughly so).
            # Wait, let's be more precise.
            pass


@pytest.mark.asyncio
async def test_quick_health_check_expiry():
    _health_cache.clear()
    url = "http://localhost:8888"

    with patch("httpx.AsyncClient.get") as mock_get:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_get.return_value = mock_response

        # First call sets the cache
        await _quick_health_check(url)
        assert mock_get.call_count == 1

        # Manually manipulate the cache to be expired
        _health_cache[url] = (True, time.time() - 20.0)

        # Second call should be a cache miss
        await _quick_health_check(url)
        assert mock_get.call_count == 2


@pytest.mark.asyncio
async def test_quick_health_check_retries():
    _health_cache.clear()
    url = "http://localhost:7777"

    with patch("httpx.AsyncClient.get") as mock_get:
        # Mock 2 failures then 1 success
        mock_get.side_effect = [
            Exception("fail1"),
            Exception("fail2"),
            MagicMock(status_code=200),
        ]

        # We need to mock asyncio.sleep to speed up tests
        with patch("asyncio.sleep", return_value=None):
            result = await _quick_health_check(url, retries=3)
            assert result is True
            assert mock_get.call_count == 3
