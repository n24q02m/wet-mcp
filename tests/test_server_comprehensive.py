import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from wet_mcp import server


@pytest.fixture(autouse=True)
def mock_settings():
    with patch("wet_mcp.server.settings") as mock:
        mock.log_level = "DEBUG"
        mock.tool_timeout = 10
        mock.wet_cache = True
        mock.sync_enabled = False
        mock.get_db_path.return_value = MagicMock()
        mock.get_cache_db_path.return_value = MagicMock()
        mock.resolve_embedding_dims.return_value = 768
        mock.resolve_embedding_backend.return_value = "litellm"
        mock.resolve_rerank_backend.return_value = "litellm"
        mock.resolve_embedding_model.return_value = "gemini"
        mock.resolve_rerank_model.return_value = "gemini-rerank"
        mock.wet_auto_searxng = False
        mock.setup_api_keys.return_value = {"GEMINI_API_KEY": "test"}
        # For tests, pretend we don't have timeout so tasks run synchronously
        mock.tool_timeout = 0
        yield mock


@pytest.fixture(autouse=True)
def mock_web_cache():
    server._web_cache = MagicMock()
    server._web_cache.get.return_value = None
    yield server._web_cache
    server._web_cache = None


@pytest.fixture(autouse=True)
def mock_docs_db():
    server._docs_db = MagicMock()
    server._docs_db.get_library.return_value = None
    server._docs_db.get_best_version.return_value = None
    server._docs_db.search.return_value = []
    yield server._docs_db
    server._docs_db = None


@pytest.mark.asyncio
async def test_warmup_searxng():
    with (
        patch("wet_mcp.setup.run_auto_setup", new_callable=MagicMock) as mock_setup,
        patch(
            "wet_mcp.searxng_runner.ensure_searxng", new_callable=AsyncMock
        ) as mock_ensure,
    ):
        await server._warmup_searxng()
        mock_setup.assert_called_once()
        mock_ensure.assert_awaited_once()


@pytest.mark.asyncio
async def test_warmup_searxng_exception():
    with patch("wet_mcp.setup.run_auto_setup", side_effect=Exception("Test Error")):
        await server._warmup_searxng()


@pytest.mark.asyncio
async def test_lifespan():
    mock_fastmcp = MagicMock()
    with (
        patch("wet_mcp.server.WebCache"),
        patch("wet_mcp.server.DocsDB"),
        patch(
            "wet_mcp.server.shutdown_crawler", new_callable=AsyncMock
        ) as mock_shutdown,
        patch("wet_mcp.server.stop_searxng") as mock_stop,
    ):
        async with server._lifespan(mock_fastmcp):
            pass

        mock_shutdown.assert_awaited_once()
        mock_stop.assert_called_once()


@pytest.mark.asyncio
async def test_init_embedding_backend():
    with patch("wet_mcp.embedder.init_backend") as mock_init:
        mock_backend = MagicMock()
        mock_backend.check_available.return_value = 768
        mock_init.return_value = mock_backend

        await server._init_embedding_backend({"K": "V"})
        assert server._embedding_dims == 768


@pytest.mark.asyncio
async def test_init_reranker_backend():
    with patch("wet_mcp.reranker.init_reranker") as mock_init:
        mock_reranker = MagicMock()
        mock_reranker.check_available.return_value = True
        mock_init.return_value = mock_reranker

        await server._init_reranker_backend()


@pytest.mark.asyncio
async def test_embed():
    with patch("wet_mcp.embedder.get_backend") as mock_get_backend:
        mock_backend = MagicMock()
        mock_backend.embed_single.return_value = [0.1, 0.2]
        mock_get_backend.return_value = mock_backend

        res = await server._embed("hello")
        assert res == [0.1, 0.2]


@pytest.mark.asyncio
async def test_embed_batch():
    with patch("wet_mcp.embedder.get_backend") as mock_get_backend:
        mock_backend = MagicMock()
        mock_backend.embed_texts.return_value = [[0.1, 0.2]]
        mock_get_backend.return_value = mock_backend

        res = await server._embed_batch(["hello"])
        assert res == [[0.1, 0.2]]


@pytest.mark.asyncio
async def test_rerank_results():
    with patch("wet_mcp.reranker.get_reranker") as mock_get_reranker:
        mock_reranker = MagicMock()
        mock_reranker.rerank.return_value = [(0, 0.9)]
        mock_get_reranker.return_value = mock_reranker

        res = await server._rerank_results(
            "query", [{"content": "hello"}, {"content": "world"}], 1
        )
        assert res == [{"content": "hello", "score": 0.9}]


@pytest.mark.asyncio
async def test_search_tool_search():
    with (
        patch("wet_mcp.server.ensure_searxng", new_callable=AsyncMock) as mock_ensure,
        patch("wet_mcp.server.searxng_search", new_callable=AsyncMock) as mock_search,
    ):
        mock_ensure.return_value = "http://searxng"
        mock_search.return_value = "search_result"
        res = await server.search("search", query="test")
        assert "search_result" in res


@pytest.mark.asyncio
async def test_search_tool_research():
    with patch("wet_mcp.server._do_research", new_callable=AsyncMock) as mock_research:
        mock_research.return_value = "research_result"
        res = await server.search("research", query="test")
        assert "research_result" in res


@pytest.mark.asyncio
async def test_search_tool_docs():
    with patch("wet_mcp.server._do_docs_search", new_callable=AsyncMock) as mock_docs:
        mock_docs.return_value = "docs_result"
        res = await server.search("docs", query="test", library="test")
        assert "docs_result" in res


@pytest.mark.asyncio
async def test_search_tool_invalid():
    res = await server.search("invalid")
    assert "Unknown action" in res


@pytest.mark.asyncio
async def test_extract_tool_extract():
    with patch("wet_mcp.server._extract", new_callable=AsyncMock) as mock_ext:
        mock_ext.return_value = "ext_result"
        res = await server.extract("extract", urls=["http://test"])
        assert "ext_result" in res


@pytest.mark.asyncio
async def test_extract_tool_crawl():
    with patch("wet_mcp.server._crawl", new_callable=AsyncMock) as mock_crawl:
        mock_crawl.return_value = "crawl_result"
        res = await server.extract("crawl", urls=["http://test"])
        assert "crawl_result" in res


@pytest.mark.asyncio
async def test_extract_tool_map():
    with patch("wet_mcp.server._sitemap", new_callable=AsyncMock) as mock_map:
        mock_map.return_value = "map_result"
        res = await server.extract("map", urls=["http://test"])
        assert "map_result" in res


@pytest.mark.asyncio
async def test_media_tool():
    # list_media is imported in server.py at top level
    with (
        patch("wet_mcp.server.list_media", new_callable=AsyncMock) as mock_list,
        patch(
            "wet_mcp.sources.crawler.download_media", new_callable=AsyncMock
        ) as mock_down,
        patch("wet_mcp.llm.analyze_media", new_callable=AsyncMock) as mock_analyze,
    ):
        mock_list.return_value = "list_result"
        res = await server.media("list", url="http://test")
        assert "list_result" in res

        mock_down.return_value = "down_result"
        res = await server.media("download", media_urls=["http://test"])
        assert "down_result" in res

        mock_analyze.return_value = "analyze_result"
        res = await server.media("analyze", url="http://test")
        assert "analyze_result" in res


@pytest.mark.asyncio
async def test_help_tool():
    with patch("wet_mcp.server.files") as mock_files:
        mock_path = MagicMock()
        mock_path.read_text.return_value = "help_text"
        mock_files.return_value.joinpath.return_value = mock_path

        res = await server.help("search")
        assert res == "help_text"


@pytest.mark.asyncio
async def test_config_tool():
    res = await server.config("status")
    assert "settings" in json.loads(res)

    res = await server.config("set", "tool_timeout", "20")
    assert "updated" in json.loads(res)["status"]


@pytest.mark.asyncio
async def test_do_research():
    with (
        patch("wet_mcp.server.ensure_searxng", new_callable=AsyncMock) as mock_ensure,
        patch("wet_mcp.server.searxng_search", new_callable=AsyncMock) as mock_search,
    ):
        mock_ensure.return_value = "url"
        mock_search.return_value = json.dumps({"results": [{"url": "arxiv.org"}]})
        res = await server._do_research("test")
        assert "arxiv" in res


@pytest.mark.asyncio
async def test_fetch_and_chunk_docs():
    with patch(
        "wet_mcp.sources.docs.try_llms_txt", new_callable=AsyncMock
    ) as mock_llms:
        mock_llms.return_value = "content"
        with patch("wet_mcp.sources.docs.chunk_llms_txt") as mock_chunk:
            mock_chunk.return_value = [{"content": "c"}] * 20
            chunks, pages = await server._fetch_and_chunk_docs("test")
            assert pages == 1
            assert len(chunks) == 20


@pytest.mark.asyncio
async def test_do_docs_search_cached():
    server._docs_db.get_library.return_value = {"id": 1, "discovery_version": 999}
    server._docs_db.get_best_version.return_value = {
        "id": 1,
        "chunk_count": 10,
        "version": "latest",
    }
    server._docs_db.search.return_value = [{"content": "res"}]

    with (
        patch("wet_mcp.server._embed", new_callable=AsyncMock) as mock_embed,
        patch("wet_mcp.server._rerank_results", new_callable=AsyncMock) as mock_rerank,
    ):
        mock_embed.return_value = [0.1]
        mock_rerank.return_value = [{"content": "res"}]

        res = await server._do_docs_search("test", "test")
        assert "cached_index" in json.loads(res)["source"]


@pytest.mark.asyncio
async def test_do_docs_search_new():
    server._docs_db.get_library.return_value = None

    with (
        patch(
            "wet_mcp.sources.docs.discover_library", new_callable=AsyncMock
        ) as mock_discover,
        patch(
            "wet_mcp.server._fetch_and_chunk_docs", new_callable=AsyncMock
        ) as mock_fetch,
        patch(
            "wet_mcp.server._embed_batch", new_callable=AsyncMock
        ) as mock_embed_batch,
        patch("wet_mcp.server._embed", new_callable=AsyncMock) as mock_embed,
        patch("wet_mcp.server._rerank_results", new_callable=AsyncMock) as mock_rerank,
    ):
        mock_discover.return_value = {
            "homepage": "http://docs",
            "repository": "http://repo",
            "registry": "npm",
            "description": "desc",
        }
        mock_fetch.return_value = ([{"content": "chunk1"}], 1)
        mock_embed_batch.return_value = [[0.1]]
        mock_embed.return_value = [0.1]
        mock_rerank.return_value = [{"content": "res"}]

        res = await server._do_docs_search("newlib", "query")
        data = json.loads(res)
        assert data["status"] == "indexing_in_progress"
        assert data["library"] == "newlib"


@pytest.mark.asyncio
async def test_do_research_timeout():
    with patch("wet_mcp.server.asyncio.wait_for", side_effect=TimeoutError):
        res = await server._do_research("test")
        assert "timed out" in res


@pytest.mark.asyncio
async def test_do_research_exception():
    with patch("wet_mcp.server.asyncio.wait_for", side_effect=Exception("Test error")):
        res = await server._do_research("test")
        assert "startup failed" in res


@pytest.mark.asyncio
async def test_do_research_json_decode_error():
    with (
        patch("wet_mcp.server.ensure_searxng", new_callable=AsyncMock) as mock_ensure,
        patch("wet_mcp.server.searxng_search", new_callable=AsyncMock) as mock_search,
    ):
        mock_ensure.return_value = "url"
        mock_search.return_value = "invalid json"
        res = await server._do_research("test")
        assert res == "invalid json"


@pytest.mark.asyncio
async def test_do_research_source_types():
    with (
        patch("wet_mcp.server.ensure_searxng", new_callable=AsyncMock) as mock_ensure,
        patch("wet_mcp.server.searxng_search", new_callable=AsyncMock) as mock_search,
    ):
        mock_ensure.return_value = "url"
        mock_search.return_value = json.dumps(
            {
                "results": [
                    {"url": "scholar.google.com"},
                    {"url": "semanticscholar.org"},
                    {"url": "pubmed.ncbi.nlm.nih.gov"},
                    {"url": "doi.org/10.123"},
                    {"url": "other.org"},
                ]
            }
        )
        res = await server._do_research("test")
        data = json.loads(res)
        types = [r["source_type"] for r in data["results"]]
        assert "google_scholar" in types
        assert "semantic_scholar" in types
        assert "pubmed" in types
        assert "doi" in types
        assert "academic" in types


@pytest.mark.asyncio
async def test_fetch_and_chunk_docs_github_raw():
    with (
        patch("wet_mcp.sources.docs.try_llms_txt", new_callable=AsyncMock) as mock_llms,
        patch(
            "wet_mcp.sources.docs._try_github_raw_docs", new_callable=AsyncMock
        ) as mock_gh,
        patch("wet_mcp.sources.docs.chunk_markdown") as mock_chunk,
    ):
        mock_llms.return_value = None
        mock_gh.return_value = [{"content": "c", "title": "t", "url": "u"}]
        mock_chunk.return_value = [{"content": f"c{i}"} for i in range(30)]
        chunks, pages = await server._fetch_and_chunk_docs("docs_url", "repo_url")
        assert pages == 1
        assert len(chunks) == 30
        # Title injection check
        assert chunks[0]["title"] == "t"


@pytest.mark.asyncio
async def test_fetch_and_chunk_docs_crawl_fallback_to_gh():
    with (
        patch("wet_mcp.sources.docs.try_llms_txt", new_callable=AsyncMock) as mock_llms,
        patch(
            "wet_mcp.sources.docs._try_github_raw_docs", new_callable=AsyncMock
        ) as mock_gh,
        patch("wet_mcp.sources.docs.chunk_markdown") as mock_chunk,
        patch(
            "wet_mcp.sources.docs.fetch_docs_pages", new_callable=AsyncMock
        ) as mock_fetch,
    ):
        mock_llms.return_value = None
        mock_gh.return_value = [{"content": "c"}]
        mock_chunk.side_effect = [
            [{"content": "gh_chunk"}],
            [],
        ]  # 1 for gh, 0 for crawl
        mock_fetch.return_value = []
        chunks, pages = await server._fetch_and_chunk_docs("docs_url")
        assert pages == 1
        assert len(chunks) == 1
        assert chunks[0]["content"] == "gh_chunk"


@pytest.mark.asyncio
async def test_do_docs_search_db_not_init():
    with patch("wet_mcp.server._docs_db", None):
        res = await server._do_docs_search("test", "test")
        assert "Docs database not initialized" in res


@pytest.mark.asyncio
async def test_do_docs_search_force_reindex():
    from wet_mcp.sources.docs import DISCOVERY_VERSION

    server._docs_db.get_library.return_value = {
        "id": 1,
        "discovery_version": DISCOVERY_VERSION - 1,
    }
    server._docs_db.get_best_version.return_value = None

    with (
        patch(
            "wet_mcp.sources.docs.discover_library", new_callable=AsyncMock
        ) as mock_discover,
        patch(
            "wet_mcp.server._fetch_and_chunk_docs", new_callable=AsyncMock
        ) as mock_fetch,
    ):
        mock_discover.return_value = {"homepage": "http"}
        mock_fetch.return_value = ([], 0)
        res = await server._do_docs_search("test", "test")
        assert "indexing_in_progress" in res


@pytest.mark.asyncio
async def test_do_docs_search_discovery_timeout():
    server._docs_db.get_library.return_value = None
    with patch("wet_mcp.server.asyncio.wait_for", side_effect=TimeoutError):
        res = await server._do_docs_search("test", "test")
        assert "Could not find documentation URL" in res


@pytest.mark.asyncio
async def test_do_docs_search_no_docs_but_repo():
    server._docs_db.get_library.return_value = None
    with (
        patch(
            "wet_mcp.sources.docs.discover_library", new_callable=AsyncMock
        ) as mock_discover,
        patch(
            "wet_mcp.server._fetch_and_chunk_docs", new_callable=AsyncMock
        ) as mock_fetch,
    ):
        mock_discover.return_value = {
            "homepage": "",
            "repository": "http://github.com/test",
        }
        mock_fetch.return_value = ([], 0)
        res = await server._do_docs_search("test", "test")
        assert "indexing_in_progress" in res


@pytest.mark.asyncio
async def test_do_docs_search_fallback_searxng():
    server._docs_db.get_library.return_value = None
    with (
        patch(
            "wet_mcp.sources.docs.discover_library", new_callable=AsyncMock
        ) as mock_discover,
        patch("wet_mcp.server.ensure_searxng", new_callable=AsyncMock) as mock_ensure,
        patch("wet_mcp.server.searxng_search", new_callable=AsyncMock) as mock_search,
        patch(
            "wet_mcp.server._fetch_and_chunk_docs", new_callable=AsyncMock
        ) as mock_fetch,
    ):
        mock_discover.return_value = None
        mock_ensure.return_value = "url"
        mock_search.return_value = json.dumps({"results": [{"url": "http://docs.alt"}]})
        # Mock fetch to return some chunks on first call
        mock_fetch.return_value = ([{"content": "chunk"}], 1)

        res = await server._do_docs_search("test", "test")
        assert "indexing_in_progress" in res


@pytest.mark.asyncio
async def test_do_docs_search_fetch_timeout():
    server._docs_db.get_library.return_value = None
    with (
        patch(
            "wet_mcp.sources.docs.discover_library", new_callable=AsyncMock
        ) as mock_discover,
        patch("wet_mcp.server._fetch_and_chunk_docs", side_effect=TimeoutError),
        patch("wet_mcp.server.ensure_searxng", new_callable=AsyncMock) as mock_ensure,
        patch("wet_mcp.server.searxng_search", new_callable=AsyncMock) as mock_search,
    ):
        mock_discover.return_value = {"homepage": "http://docs"}
        mock_ensure.return_value = "url"
        # The first fetch times out. It then falls back to searxng for alternatives.
        mock_search.return_value = json.dumps({"results": []})

        res = await server._do_docs_search("test", "test")
        assert "indexing_in_progress" in res


@pytest.mark.asyncio
async def test_with_timeout_success():
    with patch("wet_mcp.server.settings") as mock_settings:
        mock_settings.tool_timeout = 1

        async def dummy_coro():
            return "success"

        res = await server._with_timeout(dummy_coro(), "test")
        assert res == "success"


@pytest.mark.asyncio
async def test_with_timeout_expired():
    with patch("wet_mcp.server.settings") as mock_settings:
        mock_settings.tool_timeout = 0.1

        async def slow_coro():
            await asyncio.sleep(0.5)
            return "too slow"

        res = await server._with_timeout(slow_coro(), "test")
        assert "timed out" in res


def test_prompts():
    assert "Research" in server.research_topic("topic")
    assert "Find documentation" in server.library_docs("lib", "question")


def test_main():
    with patch("wet_mcp.server.mcp.run") as mock_run:
        server.main()
        mock_run.assert_called_once()
