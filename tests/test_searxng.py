"""Tests for URL normalization and per-domain result cap in SearXNG search."""

import json
import unittest.mock

import pytest

from wet_mcp.sources.searxng import (
    _apply_domain_cap,
    _build_filtered_query,
    _normalize_url,
    search,
)

# --- _normalize_url tests ---


class TestNormalizeUrl:
    def test_strip_www_prefix(self):
        assert (
            _normalize_url("https://www.example.com/page") == "https://example.com/page"
        )

    def test_no_www_unchanged(self):
        assert _normalize_url("https://example.com/page") == "https://example.com/page"

    def test_strip_trailing_slash(self):
        assert _normalize_url("https://example.com/") == "https://example.com"

    def test_strip_trailing_slash_with_path(self):
        assert _normalize_url("https://example.com/page/") == "https://example.com/page"

    def test_remove_utm_source(self):
        result = _normalize_url("https://example.com/page?utm_source=google&key=val")
        assert "utm_source" not in result
        assert "key=val" in result

    def test_remove_utm_medium(self):
        result = _normalize_url("https://example.com?utm_medium=cpc")
        assert "utm_medium" not in result

    def test_remove_utm_campaign(self):
        result = _normalize_url("https://example.com?utm_campaign=spring")
        assert "utm_campaign" not in result

    def test_remove_utm_term(self):
        result = _normalize_url("https://example.com?utm_term=shoes")
        assert "utm_term" not in result

    def test_remove_utm_content(self):
        result = _normalize_url("https://example.com?utm_content=banner")
        assert "utm_content" not in result

    def test_remove_fbclid(self):
        result = _normalize_url("https://example.com?fbclid=abc123")
        assert "fbclid" not in result

    def test_remove_gclid(self):
        result = _normalize_url("https://example.com?gclid=xyz")
        assert "gclid" not in result

    def test_remove_msclkid(self):
        result = _normalize_url("https://example.com?msclkid=abc")
        assert "msclkid" not in result

    def test_remove_yclid(self):
        result = _normalize_url("https://example.com?yclid=abc")
        assert "yclid" not in result

    def test_remove_ref(self):
        result = _normalize_url("https://example.com?ref=twitter")
        assert "ref" not in result

    def test_remove_ga_gl(self):
        result = _normalize_url("https://example.com?_ga=123&_gl=456")
        assert "_ga" not in result
        assert "_gl" not in result

    def test_remove_mc_params(self):
        result = _normalize_url("https://example.com?mc_cid=abc&mc_eid=def")
        assert "mc_cid" not in result
        assert "mc_eid" not in result

    def test_remove_multiple_tracking_params(self):
        url = "https://example.com/page?utm_source=google&utm_medium=cpc&fbclid=abc&real=value"
        result = _normalize_url(url)
        assert "utm_source" not in result
        assert "utm_medium" not in result
        assert "fbclid" not in result
        assert "real=value" in result

    def test_preserve_meaningful_params(self):
        url = "https://example.com/search?q=python&page=2&lang=en"
        result = _normalize_url(url)
        assert "q=python" in result
        assert "page=2" in result
        assert "lang=en" in result

    def test_all_params_removed_no_question_mark(self):
        result = _normalize_url("https://example.com/page?utm_source=google")
        assert result == "https://example.com/page"

    def test_combined_www_slash_tracking(self):
        url = "https://www.example.com/page/?utm_source=google&fbclid=abc"
        result = _normalize_url(url)
        assert result == "https://example.com/page"

    def test_empty_url(self):
        assert _normalize_url("") == ""

    def test_url_without_scheme(self):
        # Should handle gracefully even if urlparse gives odd results
        result = _normalize_url("example.com/page")
        assert isinstance(result, str)


# --- _apply_domain_cap tests ---


class TestApplyDomainCap:
    def test_limits_per_domain(self):
        items = [
            {"url": f"https://example.com/page{i}", "title": f"Page {i}"}
            for i in range(5)
        ]
        result = _apply_domain_cap(items)
        assert len(result) == 3

    def test_preserves_diversity(self):
        items = [
            {"url": "https://a.com/1", "title": "A1"},
            {"url": "https://b.com/1", "title": "B1"},
            {"url": "https://a.com/2", "title": "A2"},
            {"url": "https://c.com/1", "title": "C1"},
            {"url": "https://a.com/3", "title": "A3"},
            {"url": "https://a.com/4", "title": "A4"},
            {"url": "https://b.com/2", "title": "B2"},
        ]
        result = _apply_domain_cap(items)
        # A has 4, capped to 3; B has 2; C has 1 => total 6
        assert len(result) == 6
        a_count = sum(1 for r in result if "a.com" in r["url"])
        assert a_count == 3

    def test_www_stripped_for_domain_grouping(self):
        items = [
            {"url": "https://www.example.com/1", "title": "1"},
            {"url": "https://example.com/2", "title": "2"},
            {"url": "https://www.example.com/3", "title": "3"},
            {"url": "https://example.com/4", "title": "4"},
        ]
        result = _apply_domain_cap(items)
        assert len(result) == 3

    def test_empty_list(self):
        assert _apply_domain_cap([]) == []

    def test_under_cap_unchanged(self):
        items = [
            {"url": "https://a.com/1", "title": "1"},
            {"url": "https://b.com/1", "title": "2"},
        ]
        result = _apply_domain_cap(items)
        assert len(result) == 2

    def test_preserves_order(self):
        items = [
            {"url": "https://a.com/1", "title": "A1"},
            {"url": "https://b.com/1", "title": "B1"},
            {"url": "https://a.com/2", "title": "A2"},
        ]
        result = _apply_domain_cap(items)
        assert [r["title"] for r in result] == ["A1", "B1", "A2"]


# --- Integration: search() uses normalization + domain cap ---


@pytest.fixture(autouse=True)
def mock_health_check():
    with unittest.mock.patch(
        "wet_mcp.sources.searxng._ensure_searxng_healthy",
        new_callable=unittest.mock.AsyncMock,
    ) as mock_healthy:
        mock_healthy.side_effect = lambda url: url
        yield mock_healthy


@pytest.fixture
def mock_httpx_client():
    with unittest.mock.patch(
        "wet_mcp.sources.searxng.httpx.AsyncClient"
    ) as mock_client:
        yield mock_client


def _make_mock_response(results):
    mock_response = unittest.mock.Mock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"results": results}
    return mock_response


def _make_mock_client(mock_httpx_client, mock_response):
    mock_context = unittest.mock.AsyncMock()
    mock_context.get.return_value = mock_response
    mock_context.__aenter__.return_value = mock_context
    mock_httpx_client.return_value = mock_context
    return mock_context


async def test_search_dedup_normalizes_urls(mock_httpx_client):
    """URLs differing only by www/trailing slash/tracking params should be deduped."""
    results = [
        {
            "url": "https://www.example.com/page/?utm_source=google",
            "title": "Page Title",
            "content": "Short snippet",
            "engine": "google",
        },
        {
            "url": "https://example.com/page",
            "title": "Page Title",
            "content": "Longer snippet with more detail here",
            "engine": "bing",
        },
    ]
    mock_response = _make_mock_response(results)
    _make_mock_client(mock_httpx_client, mock_response)

    result = await search(
        searxng_url="http://localhost:8080",
        query="normalize_test",
        max_results=10,
    )

    data = json.loads(result)
    assert data["total"] == 1
    # Should keep longer snippet
    assert "more detail" in data["results"][0]["snippet"]
    # Sources merged
    assert "google" in data["results"][0]["source"]
    assert "bing" in data["results"][0]["source"]


async def test_search_domain_cap_applied(mock_httpx_client):
    """More than 3 results from the same domain should be capped."""
    results = [
        {
            "url": f"https://example.com/page{i}",
            "title": f"Page {i}",
            "content": f"Content {i}",
            "engine": "google",
        }
        for i in range(6)
    ]
    mock_response = _make_mock_response(results)
    _make_mock_client(mock_httpx_client, mock_response)

    result = await search(
        searxng_url="http://localhost:8080",
        query="domain_cap_test",
        max_results=10,
    )

    data = json.loads(result)
    assert data["total"] == 3


async def test_search_domain_cap_preserves_diversity(mock_httpx_client):
    """Domain cap should not affect results from different domains."""
    results = [
        {
            "url": f"https://a.com/{i}",
            "title": f"A{i}",
            "content": f"Content A{i}",
            "engine": "google",
        }
        for i in range(5)
    ] + [
        {
            "url": f"https://b.com/{i}",
            "title": f"B{i}",
            "content": f"Content B{i}",
            "engine": "bing",
        }
        for i in range(2)
    ]
    mock_response = _make_mock_response(results)
    _make_mock_client(mock_httpx_client, mock_response)

    result = await search(
        searxng_url="http://localhost:8080",
        query="diversity_test",
        max_results=10,
    )

    data = json.loads(result)
    # a.com capped to 3, b.com keeps 2 = 5 total
    assert data["total"] == 5
    urls = [r["url"] for r in data["results"]]
    a_count = sum(1 for u in urls if "a.com" in u)
    b_count = sum(1 for u in urls if "b.com" in u)
    assert a_count == 3
    assert b_count == 2


# --- _build_filtered_query tests ---


class TestBuildFilteredQuery:
    def test_no_filters(self):
        assert _build_filtered_query("python tutorial") == "python tutorial"

    def test_include_domains(self):
        result = _build_filtered_query(
            "python", include_domains=["docs.python.org", "realpython.com"]
        )
        assert "site:docs.python.org" in result
        assert "site:realpython.com" in result
        assert "python" in result
        assert " OR " in result

    def test_exclude_domains(self):
        result = _build_filtered_query(
            "python", exclude_domains=["pinterest.com", "quora.com"]
        )
        assert "-site:pinterest.com" in result
        assert "-site:quora.com" in result
        assert result.startswith("python")

    def test_combined_include_exclude(self):
        result = _build_filtered_query(
            "python",
            include_domains=["docs.python.org"],
            exclude_domains=["pinterest.com"],
        )
        assert "site:docs.python.org" in result
        assert "-site:pinterest.com" in result

    def test_include_domains_capped_at_5(self):
        domains = [f"d{i}.com" for i in range(8)]
        result = _build_filtered_query("test", include_domains=domains)
        assert "site:d4.com" in result
        assert "site:d5.com" not in result

    def test_exclude_domains_capped_at_10(self):
        domains = [f"d{i}.com" for i in range(15)]
        result = _build_filtered_query("test", exclude_domains=domains)
        assert "-site:d9.com" in result
        assert "-site:d10.com" not in result

    def test_empty_lists_same_as_none(self):
        assert (
            _build_filtered_query("test", include_domains=[], exclude_domains=[])
            == "test"
        )


# --- search() with time_range and language ---


async def test_search_with_time_range(mock_httpx_client):
    """time_range param should be passed to SearXNG."""
    results = [
        {
            "url": "https://example.com/recent",
            "title": "Recent",
            "content": "Recent content",
            "engine": "google",
        },
    ]
    mock_response = _make_mock_response(results)
    mock_client = _make_mock_client(mock_httpx_client, mock_response)

    await search(
        searxng_url="http://localhost:8080",
        query="recent news",
        time_range="week",
    )

    # Verify the params passed to httpx include time_range
    call_kwargs = mock_client.get.call_args
    params = call_kwargs.kwargs.get("params") or call_kwargs[1].get("params")
    assert params["time_range"] == "week"


async def test_search_with_language(mock_httpx_client):
    """language param should be passed to SearXNG."""
    results = [
        {
            "url": "https://example.com/vi",
            "title": "Vietnamese",
            "content": "Noi dung",
            "engine": "google",
        },
    ]
    mock_response = _make_mock_response(results)
    mock_client = _make_mock_client(mock_httpx_client, mock_response)

    await search(
        searxng_url="http://localhost:8080",
        query="tin tuc",
        language="vi",
    )

    call_kwargs = mock_client.get.call_args
    params = call_kwargs.kwargs.get("params") or call_kwargs[1].get("params")
    assert params["language"] == "vi"


async def test_search_invalid_time_range_ignored(mock_httpx_client):
    """Invalid time_range should not be passed to SearXNG."""
    results = [
        {
            "url": "https://example.com/page",
            "title": "Page",
            "content": "Content",
            "engine": "google",
        },
    ]
    mock_response = _make_mock_response(results)
    mock_client = _make_mock_client(mock_httpx_client, mock_response)

    await search(
        searxng_url="http://localhost:8080",
        query="test",
        time_range="invalid",
    )

    call_kwargs = mock_client.get.call_args
    params = call_kwargs.kwargs.get("params") or call_kwargs[1].get("params")
    assert "time_range" not in params


async def test_search_with_domain_filters(mock_httpx_client):
    """include/exclude domains should modify the query sent to SearXNG."""
    results = [
        {
            "url": "https://docs.python.org/page",
            "title": "Docs",
            "content": "Python docs",
            "engine": "google",
        },
    ]
    mock_response = _make_mock_response(results)
    mock_client = _make_mock_client(mock_httpx_client, mock_response)

    await search(
        searxng_url="http://localhost:8080",
        query="python tutorial",
        include_domains=["docs.python.org"],
        exclude_domains=["pinterest.com"],
    )

    call_kwargs = mock_client.get.call_args
    params = call_kwargs.kwargs.get("params") or call_kwargs[1].get("params")
    assert "site:docs.python.org" in params["q"]
    assert "-site:pinterest.com" in params["q"]


async def test_search_preserves_original_query_in_output(mock_httpx_client):
    """Output JSON should contain the original query, not the filtered one."""
    results = [
        {
            "url": "https://example.com/page",
            "title": "Page",
            "content": "Content",
            "engine": "google",
        },
    ]
    mock_response = _make_mock_response(results)
    _make_mock_client(mock_httpx_client, mock_response)

    result = await search(
        searxng_url="http://localhost:8080",
        query="python tutorial",
        include_domains=["docs.python.org"],
    )

    data = json.loads(result)
    assert data["query"] == "python tutorial"
