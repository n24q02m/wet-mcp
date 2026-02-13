"""Tests for src/wet_mcp/cache.py — WebCache with TTL-based expiry.

Covers cache hit/miss, TTL expiry, hit counting, purge mechanics,
deterministic cache keys, get_extract cross-action lookup, and stats.
"""

import time
from unittest.mock import patch

import pytest

from wet_mcp.cache import WebCache, _cache_key


@pytest.fixture
def cache(tmp_path):
    """Create a fresh WebCache for each test."""
    cache_path = tmp_path / "test_cache.db"
    cache = WebCache(cache_path)
    yield cache
    cache.close()


@pytest.fixture
def short_ttl_cache(tmp_path):
    """Cache with very short TTL for expiry tests."""
    cache_path = tmp_path / "short_cache.db"
    cache = WebCache(cache_path, ttls={"search": 1, "extract": 1})
    yield cache
    cache.close()


# -----------------------------------------------------------------------
# Cache key determinism
# -----------------------------------------------------------------------


class TestCacheKey:
    def test_deterministic_key(self):
        """Same action + params always produce same key."""
        params = {"query": "test", "max_results": 10}
        k1 = _cache_key("search", params)
        k2 = _cache_key("search", params)
        assert k1 == k2

    def test_different_actions_different_keys(self):
        """Different actions produce different keys."""
        params = {"query": "test"}
        k1 = _cache_key("search", params)
        k2 = _cache_key("research", params)
        assert k1 != k2

    def test_param_order_irrelevant(self):
        """Key is the same regardless of dict key ordering."""
        k1 = _cache_key("search", {"a": 1, "b": 2})
        k2 = _cache_key("search", {"b": 2, "a": 1})
        assert k1 == k2

    def test_different_params_different_keys(self):
        """Different param values produce different keys."""
        k1 = _cache_key("search", {"query": "foo"})
        k2 = _cache_key("search", {"query": "bar"})
        assert k1 != k2


# -----------------------------------------------------------------------
# Get / Set basics
# -----------------------------------------------------------------------


class TestGetSet:
    def test_miss_on_empty_cache(self, cache):
        result = cache.get("search", {"query": "test"})
        assert result is None

    def test_set_and_get(self, cache):
        cache.set("search", {"query": "hello"}, "Search Results")
        result = cache.get("search", {"query": "hello"})
        assert result == "Search Results"

    def test_miss_different_params(self, cache):
        cache.set("search", {"query": "hello"}, "Results")
        result = cache.get("search", {"query": "world"})
        assert result is None

    def test_overwrite_existing(self, cache):
        """Setting same key overwrites previous value."""
        params = {"query": "test"}
        cache.set("search", params, "old")
        cache.set("search", params, "new")
        assert cache.get("search", params) == "new"


# -----------------------------------------------------------------------
# TTL expiry
# -----------------------------------------------------------------------


class TestTTLExpiry:
    def test_expired_entry_returns_none(self, short_ttl_cache):
        """Expired entries are not returned."""
        short_ttl_cache.set("search", {"query": "test"}, "Results")
        # Immediately available
        assert short_ttl_cache.get("search", {"query": "test"}) is not None

        # Mock time to be 2 seconds in the future (past 1s TTL)
        with patch("wet_mcp.cache.time.time", return_value=time.time() + 2):
            result = short_ttl_cache.get("search", {"query": "test"})
            assert result is None

    def test_different_ttls_per_action(self, tmp_path):
        """Different actions have different TTLs."""
        cache = WebCache(
            tmp_path / "ttls.db",
            ttls={"search": 60, "extract": 3600},
        )
        try:
            cache.set("search", {"q": "fast"}, "fast result")
            cache.set("extract", {"urls": ["url"]}, "slow result")

            # After 120 seconds: search expired, extract still valid
            with patch("wet_mcp.cache.time.time", return_value=time.time() + 120):
                assert cache.get("search", {"q": "fast"}) is None
                assert cache.get("extract", {"urls": ["url"]}) == "slow result"
        finally:
            cache.close()


# -----------------------------------------------------------------------
# Hit counting
# -----------------------------------------------------------------------


class TestHitCounting:
    def test_hit_count_increments(self, cache):
        """Each get() on a valid entry increments hit_count."""
        params = {"query": "popular"}
        cache.set("search", params, "Popular Results")

        # Hit 3 times
        for _ in range(3):
            cache.get("search", params)

        stats = cache.stats()
        assert stats["search"]["hits"] == 3

    def test_miss_does_not_increment(self, cache):
        """Cache misses don't affect hit count."""
        cache.set("search", {"query": "a"}, "result")
        cache.get("search", {"query": "nonexistent"})

        stats = cache.stats()
        assert stats["search"]["hits"] == 0


# -----------------------------------------------------------------------
# Purge mechanics
# -----------------------------------------------------------------------


class TestPurge:
    def test_clear_all(self, cache):
        """clear() removes all entries."""
        cache.set("search", {"q": "a"}, "r1")
        cache.set("extract", {"urls": ["b"]}, "r2")
        removed = cache.clear()
        assert removed == 2
        assert cache.get("search", {"q": "a"}) is None

    def test_clear_by_action(self, cache):
        """clear(action) only removes that action's entries."""
        cache.set("search", {"q": "a"}, "r1")
        cache.set("extract", {"urls": ["b"]}, "r2")
        removed = cache.clear("search")
        assert removed == 1
        assert cache.get("search", {"q": "a"}) is None
        assert cache.get("extract", {"urls": ["b"]}) == "r2"

    def test_purge_expired_removes_old(self, short_ttl_cache):
        """Manually trigger purge of expired entries."""
        short_ttl_cache.set("search", {"q": "old"}, "old result")
        # Force purge with time in the future
        with patch("wet_mcp.cache.time.time", return_value=time.time() + 5):
            short_ttl_cache._purge_expired()
        # Even without time mock, the entry should be gone from DB
        stats = short_ttl_cache.stats()
        assert stats.get("search", {}).get("total", 0) == 0


# -----------------------------------------------------------------------
# get_extract cross-action lookup
# -----------------------------------------------------------------------


class TestGetExtract:
    def test_get_extract_from_extract_cache(self, cache):
        """get_extract finds URL in extract cache."""
        cache.set(
            "extract",
            {
                "urls": ["https://example.com/docs"],
                "format": "markdown",
                "stealth": True,
            },
            '[{"url": "https://example.com/docs", "content": "doc content"}]',
        )
        result = cache.get_extract("https://example.com/docs")
        assert result is not None
        assert "doc content" in result

    def test_get_extract_from_crawl_cache(self, cache):
        """get_extract also searches crawl cache."""
        cache.set(
            "crawl",
            {"urls": ["https://example.com"], "depth": 2, "max_pages": 20},
            '[{"url": "https://example.com", "content": "crawled"}]',
        )
        result = cache.get_extract("https://example.com")
        assert result is not None

    def test_get_extract_miss(self, cache):
        """get_extract returns None when URL not in any cache."""
        assert cache.get_extract("https://nowhere.com") is None


# -----------------------------------------------------------------------
# Stats
# -----------------------------------------------------------------------


class TestStats:
    def test_stats_empty(self, cache):
        assert cache.stats() == {}

    def test_stats_counts(self, cache):
        cache.set("search", {"q": "a"}, "r1")
        cache.set("search", {"q": "b"}, "r2")
        cache.set("extract", {"urls": ["c"]}, "r3")

        stats = cache.stats()
        assert stats["search"]["total"] == 2
        assert stats["search"]["active"] == 2
        assert stats["extract"]["total"] == 1

    def test_stats_active_vs_expired(self, short_ttl_cache):
        """Stats distinguish active vs expired entries."""
        short_ttl_cache.set("search", {"q": "a"}, "result")

        with patch("wet_mcp.cache.time.time", return_value=time.time() + 5):
            stats = short_ttl_cache.stats()
            assert stats["search"]["total"] == 1
            assert stats["search"]["active"] == 0


# -----------------------------------------------------------------------
# Edge cases
# -----------------------------------------------------------------------


class TestCacheEdgeCases:
    def test_close_and_reopen(self, tmp_path):
        """Cache persists after close and reopen."""
        path = tmp_path / "persist.db"
        c1 = WebCache(path)
        c1.set("search", {"q": "test"}, "cached")
        c1.close()

        c2 = WebCache(path)
        assert c2.get("search", {"q": "test"}) == "cached"
        c2.close()

    def test_unicode_content(self, cache):
        """Unicode content is stored and retrieved correctly."""
        cache.set("search", {"q": "unicode"}, "Tieng Viet: Xin chao")
        result = cache.get("search", {"q": "unicode"})
        assert result == "Tieng Viet: Xin chao"

    def test_large_content(self, cache):
        """Large content (>1MB) is handled."""
        big_content = "x" * (1024 * 1024)
        cache.set("extract", {"urls": ["big"]}, big_content)
        result = cache.get("extract", {"urls": ["big"]})
        assert result == big_content
        assert len(result) == 1024 * 1024
