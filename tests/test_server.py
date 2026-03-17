"""Tests for src/wet_mcp/server.py."""

import json
from unittest.mock import AsyncMock, patch

import pytest

from wet_mcp.server import extract, search


@pytest.mark.asyncio
async def test_search_success():
    """Test search action success path."""
    with (
        patch("wet_mcp.server.ensure_searxng", new_callable=AsyncMock) as mock_ensure,
        patch("wet_mcp.server.searxng_search", new_callable=AsyncMock) as mock_search,
    ):
        mock_ensure.return_value = "http://localhost:8080"
        mock_search.return_value = "Search Results"

        result = await search(action="search", query="test query")

        assert "Search Results" in result
        assert "<untrusted_search_content>" in result
        assert "[SECURITY:" in result
        mock_ensure.assert_called_once()
        mock_search.assert_called_once_with(
            searxng_url="http://localhost:8080",
            query="test query",
            categories="general",
            max_results=30,  # 10 * _RERANK_CANDIDATE_MULTIPLIER (3)
            time_range=None,
            language=None,
            include_domains=None,
            exclude_domains=None,
        )


@pytest.mark.asyncio
async def test_search_missing_query():
    """Test search action missing query."""
    result = await search(action="search", query=None)
    assert "Error: query is required" in result


@pytest.mark.asyncio
async def test_extract_success():
    """Test extract action success path."""
    with patch("wet_mcp.server._extract", new_callable=AsyncMock) as mock_extract:
        mock_extract.return_value = "Extracted Content"

        result = await extract(action="extract", urls=["https://example.com"])

        assert "Extracted Content" in result
        assert "<untrusted_extract_content>" in result
        assert "[SECURITY:" in result
        mock_extract.assert_called_once_with(
            urls=["https://example.com"],
            format="markdown",
            stealth=False,
        )


@pytest.mark.asyncio
async def test_extract_with_options():
    """Test extract action with custom options."""
    with patch("wet_mcp.server._extract", new_callable=AsyncMock) as mock_extract:
        mock_extract.return_value = "Extracted Content"

        result = await extract(
            action="extract",
            urls=["https://example.com"],
            format="json",
            stealth=False,
        )

        assert "Extracted Content" in result
        assert "<untrusted_extract_content>" in result
        mock_extract.assert_called_once_with(
            urls=["https://example.com"],
            format="json",
            stealth=False,
        )


@pytest.mark.asyncio
async def test_extract_missing_urls():
    """Test extract action missing urls."""
    result = await extract(action="extract", urls=None)
    assert "Error: urls is required" in result


@pytest.mark.asyncio
async def test_crawl_success():
    """Test crawl action success path."""
    with patch("wet_mcp.server._crawl", new_callable=AsyncMock) as mock_crawl:
        mock_crawl.return_value = "Crawl Results"

        result = await extract(
            action="crawl",
            urls=["https://example.com"],
            depth=3,
            max_pages=50,
            format="json",
            stealth=False,
        )

        assert "Crawl Results" in result
        assert "<untrusted_extract_content>" in result
        mock_crawl.assert_called_once_with(
            urls=["https://example.com"],
            depth=3,
            max_pages=50,
            format="json",
            stealth=False,
        )


@pytest.mark.asyncio
async def test_crawl_defaults():
    """Test crawl action with defaults."""
    with patch("wet_mcp.server._crawl", new_callable=AsyncMock) as mock_crawl:
        mock_crawl.return_value = "Crawl Results"

        result = await extract(action="crawl", urls=["https://example.com"])

        assert "Crawl Results" in result
        assert "<untrusted_extract_content>" in result
        mock_crawl.assert_called_once_with(
            urls=["https://example.com"],
            depth=2,
            max_pages=20,
            format="markdown",
            stealth=False,
        )


@pytest.mark.asyncio
async def test_crawl_missing_urls():
    """Test crawl action missing urls."""
    result = await extract(action="crawl", urls=None)
    assert "Error: urls is required" in result


@pytest.mark.asyncio
async def test_map_success():
    """Test map action success path."""
    with patch("wet_mcp.server._sitemap", new_callable=AsyncMock) as mock_sitemap:
        mock_sitemap.return_value = "Sitemap Content"

        result = await extract(
            action="map", urls=["https://example.com"], depth=3, max_pages=50
        )

        assert "Sitemap Content" in result
        assert "<untrusted_extract_content>" in result
        mock_sitemap.assert_called_once_with(
            urls=["https://example.com"],
            depth=3,
            max_pages=50,
        )


@pytest.mark.asyncio
async def test_map_defaults():
    """Test map action with defaults."""
    with patch("wet_mcp.server._sitemap", new_callable=AsyncMock) as mock_sitemap:
        mock_sitemap.return_value = "Sitemap Content"

        result = await extract(action="map", urls=["https://example.com"])

        assert "Sitemap Content" in result
        assert "<untrusted_extract_content>" in result
        mock_sitemap.assert_called_once_with(
            urls=["https://example.com"],
            depth=2,
            max_pages=20,
        )


@pytest.mark.asyncio
async def test_map_missing_urls():
    """Test map action missing urls."""
    result = await extract(action="map", urls=None)
    assert "Error: urls is required" in result


@pytest.mark.asyncio
async def test_search_invalid_action():
    """Test invalid action on search tool."""
    result = await search(action="invalid_action")
    assert "Error: Unknown action" in result


@pytest.mark.asyncio
async def test_extract_invalid_action():
    """Test invalid action on extract tool."""
    result = await extract(action="invalid_action")
    assert "Error: Unknown action" in result


@pytest.mark.asyncio
async def test_search_applies_reranking():
    """Verify search action calls _rerank_results when reranker is available."""
    mock_results = json.dumps(
        {
            "results": [
                {
                    "url": f"https://example{i}.com/page",
                    "title": f"R{i}",
                    "snippet": f"Content {i}",
                    "source": "g",
                }
                for i in range(6)
            ],
            "total": 6,
            "query": "test",
        }
    )

    reranked = [
        {
            "url": "https://example2.com/page",
            "title": "R2",
            "snippet": "Content 2",
            "source": "g",
            "content": "Content 2",
            "score": 0.9,
        },
        {
            "url": "https://example0.com/page",
            "title": "R0",
            "snippet": "Content 0",
            "source": "g",
            "content": "Content 0",
            "score": 0.7,
        },
    ]

    with (
        patch(
            "wet_mcp.server.ensure_searxng",
            new_callable=AsyncMock,
            return_value="http://localhost:41592",
        ),
        patch(
            "wet_mcp.server.searxng_search",
            new_callable=AsyncMock,
            return_value=mock_results,
        ),
        patch(
            "wet_mcp.server._rerank_results",
            new_callable=AsyncMock,
            return_value=reranked,
        ) as mock_rerank,
        patch("wet_mcp.server._web_cache", None),
    ):
        result = await search(action="search", query="test", max_results=3)

        # Verify reranker was called
        mock_rerank.assert_called_once()
        call_args = mock_rerank.call_args
        assert call_args[0][0] == "test"  # query
        assert call_args[1]["top_n"] == 3  # top_n

        # Verify reranked results are used (unwrap XPIA tags)
        # Format: <tag>\n{content}\n</tag>\n\n[SECURITY:...]
        start = result.index("\n") + 1
        end = result.index("\n</untrusted_search_content>")
        data = json.loads(result[start:end])
        assert data["total"] == 2  # only 2 reranked results
        assert data["results"][0]["url"] == "https://example2.com/page"


@pytest.mark.asyncio
async def test_search_reranking_failure_falls_back():
    """When reranking fails, original results are returned."""
    mock_results = json.dumps(
        {
            "results": [
                {"url": "https://a.com", "title": "A", "snippet": "S", "source": "g"}
            ],
            "total": 1,
            "query": "test",
        }
    )

    with (
        patch(
            "wet_mcp.server.ensure_searxng",
            new_callable=AsyncMock,
            return_value="http://localhost:41592",
        ),
        patch(
            "wet_mcp.server.searxng_search",
            new_callable=AsyncMock,
            return_value=mock_results,
        ),
        patch(
            "wet_mcp.server._rerank_results",
            new_callable=AsyncMock,
            side_effect=Exception("rerank fail"),
        ),
        patch("wet_mcp.server._web_cache", None),
    ):
        result = await search(action="search", query="test", max_results=3)
        # Extract JSON from XPIA-wrapped result
        start = result.index("\n") + 1
        end = result.index("\n</untrusted_search_content>")
        data = json.loads(result[start:end])
        assert data["total"] == 1  # original result preserved
