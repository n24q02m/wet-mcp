"""Pytest configuration and fixtures."""

from unittest.mock import AsyncMock

import pytest


@pytest.fixture
def sample_url():
    """Sample URL for testing."""
    return "https://example.com"


@pytest.fixture
def sample_query():
    """Sample search query."""
    return "test query"


@pytest.fixture(autouse=True)
async def _reset_crawler_singleton():
    """Reset the crawler singleton state before and after each test.

    This ensures tests do not leak state between each other when the
    singleton browser pool is involved.
    """
    import wet_mcp.sources.crawler as crawler_mod

    # Reset before test
    crawler_mod._crawler_instance = None
    crawler_mod._crawler_stealth = False
    crawler_mod._browser_semaphore = None

    yield

    # Reset after test
    crawler_mod._crawler_instance = None
    crawler_mod._crawler_stealth = False
    crawler_mod._browser_semaphore = None


@pytest.fixture
def mock_crawler_instance():
    """Create a mock AsyncWebCrawler instance for use with _get_crawler patch.

    Returns the mock instance directly.  Tests should patch
    ``wet_mcp.sources.crawler._get_crawler`` to return this mock so that
    the singleton browser pool is bypassed entirely.

    Example usage::

        async def test_something(mock_crawler_instance):
            mock_result = MagicMock(success=True, ...)
            mock_crawler_instance.arun = AsyncMock(return_value=mock_result)

            with patch(
                "wet_mcp.sources.crawler._get_crawler",
                new_callable=AsyncMock,
                return_value=mock_crawler_instance,
            ):
                result = await extract(["https://example.com"])
    """
    instance = AsyncMock()
    instance.__aenter__ = AsyncMock(return_value=instance)
    instance.__aexit__ = AsyncMock(return_value=None)
    return instance
