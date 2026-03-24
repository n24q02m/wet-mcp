"""Additional unit tests for server.py to increase coverage to 95%+.

Targets uncovered lines: 106, 134, 136, 147-149, 172-174, 187-188,
217, 224-261, 274-275, 292-307, 325, 328, 332-334, 343, 346-348,
377-380, 511, 516-519, 535, 540, 551, 553, 615, 636, 663, 885-888,
906, 908, 1037, 1085-1092, 1109-1121, 1160-1163, 1185-1207,
1218-1249, 1254, 1289, 1304, 1390-1391, 1542.
"""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from wet_mcp import server

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _mock_settings():
    with patch("wet_mcp.server.settings") as mock:
        mock.log_level = "DEBUG"
        mock.tool_timeout = 0
        mock.wet_cache = True
        mock.sync_enabled = False
        mock.get_db_path.return_value = MagicMock()
        mock.get_cache_db_path.return_value = MagicMock()
        mock.resolve_embedding_dims.return_value = 768
        mock.resolve_embedding_backend.return_value = "litellm"
        mock.resolve_rerank_backend.return_value = "litellm"
        mock.resolve_embedding_model.return_value = "gemini"
        mock.resolve_rerank_model.return_value = "gemini-rerank"
        mock.resolve_local_embedding_model.return_value = "local-model"
        mock.resolve_local_rerank_model.return_value = "local-rerank"
        mock.wet_auto_searxng = False
        mock.setup_litellm.return_value = "sdk"
        mock.download_dir = "/tmp/downloads"
        mock.sync_remote = ""
        mock.sync_folder = ""
        mock.sync_interval = 300
        yield mock


@pytest.fixture(autouse=True)
def _mock_web_cache():
    server._web_cache = MagicMock()
    server._web_cache.get.return_value = None
    yield server._web_cache
    server._web_cache = None


@pytest.fixture(autouse=True)
def _mock_docs_db():
    server._docs_db = MagicMock()
    server._docs_db.get_library.return_value = None
    server._docs_db.get_best_version.return_value = None
    server._docs_db.search.return_value = []
    yield server._docs_db
    server._docs_db = None


# ---------------------------------------------------------------------------
# _lifespan_startup (lines 106, 134, 136, 147-149)
# ---------------------------------------------------------------------------


async def test_lifespan_startup_no_github_token():
    """Line 106: warn when no GITHUB_TOKEN set."""
    with (
        patch.dict("os.environ", {}, clear=True),
        patch("wet_mcp.server.WebCache"),
        patch("wet_mcp.server.DocsDB"),
        patch("wet_mcp.server._init_embedding_backend", new_callable=AsyncMock),
        patch("wet_mcp.server._init_reranker_backend", new_callable=AsyncMock),
        patch("wet_mcp.config.settings") as cfg,
    ):
        cfg.setup_litellm.return_value = "sdk"
        cfg.wet_auto_searxng = False
        cfg.wet_cache = False
        cfg.sync_enabled = False
        cfg.resolve_embedding_dims.return_value = 768
        cfg.get_db_path.return_value = MagicMock()
        task = await server._lifespan_startup()
        assert task is None  # wet_auto_searxng is False


async def test_lifespan_startup_with_auto_searxng():
    """Line 117: creates warmup task when auto_searxng is True."""
    with (
        patch.dict("os.environ", {"GITHUB_TOKEN": "tok"}, clear=False),
        patch("wet_mcp.server.WebCache"),
        patch("wet_mcp.server.DocsDB"),
        patch("wet_mcp.server._init_embedding_backend", new_callable=AsyncMock),
        patch("wet_mcp.server._init_reranker_backend", new_callable=AsyncMock),
        patch("wet_mcp.server._warmup_searxng", new_callable=AsyncMock),
        patch("wet_mcp.config.settings") as cfg,
    ):
        cfg.setup_litellm.return_value = "sdk"
        cfg.wet_auto_searxng = True
        cfg.wet_cache = False
        cfg.sync_enabled = False
        cfg.resolve_embedding_dims.return_value = 768
        cfg.get_db_path.return_value = MagicMock()
        task = await server._lifespan_startup()
        assert task is not None
        # Clean up the task
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass


async def test_lifespan_startup_backends_init_failure():
    """Lines 134-136: background backend init logs error on failure."""
    with (
        patch.dict("os.environ", {"GITHUB_TOKEN": "tok"}, clear=False),
        patch("wet_mcp.server.WebCache"),
        patch("wet_mcp.server.DocsDB"),
        patch(
            "wet_mcp.server._init_embedding_backend",
            new_callable=AsyncMock,
            side_effect=Exception("backend fail"),
        ),
        patch("wet_mcp.config.settings") as cfg,
    ):
        cfg.setup_litellm.return_value = "sdk"
        cfg.wet_auto_searxng = False
        cfg.wet_cache = False
        cfg.sync_enabled = False
        cfg.resolve_embedding_dims.return_value = 768
        cfg.get_db_path.return_value = MagicMock()
        await server._lifespan_startup()
        # Allow the background task to run
        await asyncio.sleep(0.05)


async def test_lifespan_startup_sync_enabled():
    """Lines 147-149: start auto-sync when sync_enabled."""
    with (
        patch.dict("os.environ", {"GITHUB_TOKEN": "tok"}, clear=False),
        patch("wet_mcp.server.WebCache"),
        patch("wet_mcp.server.DocsDB"),
        patch("wet_mcp.server._init_embedding_backend", new_callable=AsyncMock),
        patch("wet_mcp.server._init_reranker_backend", new_callable=AsyncMock),
        patch("wet_mcp.sync.start_auto_sync") as mock_sync,
        patch("wet_mcp.config.settings") as cfg,
    ):
        cfg.setup_litellm.return_value = "sdk"
        cfg.wet_auto_searxng = False
        cfg.wet_cache = False
        cfg.sync_enabled = True
        cfg.resolve_embedding_dims.return_value = 768
        cfg.get_db_path.return_value = MagicMock()
        await server._lifespan_startup()
        mock_sync.assert_called_once()


# ---------------------------------------------------------------------------
# _lifespan_shutdown (lines 172-174, 187-188)
# ---------------------------------------------------------------------------


async def test_lifespan_shutdown_sync_enabled():
    """Lines 172-174: stop auto-sync on shutdown."""
    with (
        patch("wet_mcp.server.shutdown_crawler", new_callable=AsyncMock),
        patch("wet_mcp.server.stop_searxng"),
        patch("wet_mcp.sync.stop_auto_sync") as mock_stop,
        patch("wet_mcp.config.settings") as cfg,
    ):
        cfg.sync_enabled = True
        await server._lifespan_shutdown(None)
        mock_stop.assert_called_once()


async def test_lifespan_shutdown_browser_error():
    """Lines 187-188: shutdown_crawler error is non-fatal."""
    with (
        patch(
            "wet_mcp.server.shutdown_crawler",
            new_callable=AsyncMock,
            side_effect=Exception("browser err"),
        ),
        patch("wet_mcp.server.stop_searxng"),
    ):
        # Should not raise
        await server._lifespan_shutdown(None)


async def test_lifespan_shutdown_cancel_warmup_task():
    """Lines 161-166: cancel in-progress warmup task."""

    async def _never_complete() -> None:
        await asyncio.Future()

    task = asyncio.create_task(_never_complete())
    with (
        patch("wet_mcp.server.shutdown_crawler", new_callable=AsyncMock),
        patch("wet_mcp.server.stop_searxng"),
    ):
        await server._lifespan_shutdown(task)
    assert task.cancelled() or task.done()


# ---------------------------------------------------------------------------
# _init_embedding_backend (lines 217, 224-261)
# ---------------------------------------------------------------------------


async def test_init_embedding_litellm_explicit_model_success():
    """Lines 206-222: litellm with explicit model, successful init."""
    with patch("wet_mcp.embedder.init_backend") as mock_init:
        mock_backend = MagicMock()
        mock_backend.check_available.return_value = 1024
        mock_init.return_value = mock_backend

        server._embedding_dims = 0
        await server._init_embedding_backend("sdk")
        assert server._embedding_dims == 768  # _DEFAULT_EMBEDDING_DIMS


async def test_init_embedding_litellm_explicit_model_failure_fallback_local():
    """Lines 224, 247-261: explicit model fails, falls back to local."""
    call_count = 0

    def fake_init_backend(backend_type, model, **kwargs):
        nonlocal call_count
        call_count += 1
        if backend_type == "litellm":
            raise Exception("cloud unavailable")
        mock_b = MagicMock()
        mock_b.check_available.return_value = 384
        return mock_b

    with patch("wet_mcp.embedder.init_backend", side_effect=fake_init_backend):
        await server._init_embedding_backend("sdk")
        assert call_count == 2  # litellm + local


async def test_init_embedding_litellm_autodetect(_mock_settings):
    """Lines 225-242: auto-detect candidate models when no explicit model."""
    _mock_settings.resolve_embedding_model.return_value = None
    _mock_settings.resolve_embedding_backend.return_value = "litellm"

    attempts = []

    def fake_init(backend_type, model, **kwargs):
        attempts.append(model)
        if model == "text-embedding-3-large":
            mock_b = MagicMock()
            mock_b.check_available.return_value = 3072
            return mock_b
        raise Exception("not available")

    with patch("wet_mcp.embedder.init_backend", side_effect=fake_init):
        server._embedding_dims = 0
        await server._init_embedding_backend("sdk")
        # First candidate fails, second succeeds
        assert "gemini/gemini-embedding-001" in attempts
        assert "text-embedding-3-large" in attempts


async def test_init_embedding_litellm_autodetect_all_fail_local_fallback(
    _mock_settings,
):
    """Lines 244-261: all candidates fail, uses local backend."""
    _mock_settings.resolve_embedding_model.return_value = None
    _mock_settings.resolve_embedding_backend.return_value = "litellm"

    def fake_init(backend_type, model, **kwargs):
        if backend_type == "litellm":
            raise Exception("not available")
        mock_b = MagicMock()
        mock_b.check_available.return_value = 384
        return mock_b

    with patch("wet_mcp.embedder.init_backend", side_effect=fake_init):
        await server._init_embedding_backend("sdk")


async def test_init_embedding_local_zero_dims():
    """Lines 258-259: local backend returns 0 dims."""
    with patch("wet_mcp.embedder.init_backend") as mock_init:
        # First call for litellm fails
        mock_backend_cloud = MagicMock()
        mock_backend_cloud.check_available.side_effect = Exception("no cloud")
        mock_backend_local = MagicMock()
        mock_backend_local.check_available.return_value = 0

        mock_init.side_effect = [
            Exception("cloud fail"),
            mock_backend_local,
        ]

        _mock_settings = MagicMock()
        with patch("wet_mcp.server.settings") as ms:
            ms.resolve_embedding_backend.return_value = "local"
            ms.resolve_local_embedding_model.return_value = "test"
            ms.resolve_embedding_dims.return_value = 768

            await server._init_embedding_backend("sdk")


async def test_init_embedding_local_exception(_mock_settings):
    """Lines 260-261: local init raises exception."""
    _mock_settings.resolve_embedding_backend.return_value = "local"

    with patch("wet_mcp.embedder.init_backend", side_effect=Exception("onnx fail")):
        await server._init_embedding_backend("sdk")


# ---------------------------------------------------------------------------
# _init_reranker_backend (lines 274-275, 292-307)
# ---------------------------------------------------------------------------


async def test_init_reranker_disabled(_mock_settings):
    """Lines 274-275: reranking disabled."""
    _mock_settings.resolve_rerank_backend.return_value = None
    await server._init_reranker_backend("sdk")


async def test_init_reranker_litellm_success(_mock_settings):
    """Lines 281-291: litellm reranker, successful."""
    _mock_settings.resolve_rerank_backend.return_value = "litellm"
    _mock_settings.resolve_rerank_model.return_value = "cohere-rerank"

    with patch("wet_mcp.reranker.init_reranker") as mock_init:
        mock_reranker = MagicMock()
        mock_reranker.check_available.return_value = True
        mock_init.return_value = mock_reranker

        await server._init_reranker_backend("sdk")


async def test_init_reranker_litellm_fail_fallback_local(_mock_settings):
    """Lines 292-307: cloud reranker fails, falls back to local."""
    _mock_settings.resolve_rerank_backend.return_value = "litellm"
    _mock_settings.resolve_rerank_model.return_value = "cohere-rerank"

    call_count = 0

    def fake_init(backend_type, model, **kwargs):
        nonlocal call_count
        call_count += 1
        if backend_type == "litellm":
            raise Exception("cloud unavailable")
        mock_r = MagicMock()
        mock_r.check_available.return_value = True
        return mock_r

    with patch("wet_mcp.reranker.init_reranker", side_effect=fake_init):
        await server._init_reranker_backend("sdk")
        assert call_count == 2


async def test_init_reranker_local_not_available(_mock_settings):
    """Lines 304-305: local reranker returns False for check_available."""
    _mock_settings.resolve_rerank_backend.return_value = "local"

    with patch("wet_mcp.reranker.init_reranker") as mock_init:
        mock_r = MagicMock()
        mock_r.check_available.return_value = False
        mock_init.return_value = mock_r

        await server._init_reranker_backend("sdk")


async def test_init_reranker_local_exception(_mock_settings):
    """Lines 306-307: local reranker init fails."""
    _mock_settings.resolve_rerank_backend.return_value = "local"

    with patch(
        "wet_mcp.reranker.init_reranker", side_effect=Exception("reranker fail")
    ):
        await server._init_reranker_backend("sdk")


# ---------------------------------------------------------------------------
# _embed (lines 325, 328, 332-334)
# ---------------------------------------------------------------------------


async def test_embed_query_qwen3_backend():
    """Lines 327-330: query embedding with Qwen3EmbedBackend."""
    with patch("wet_mcp.embedder.get_backend") as mock_get:
        from wet_mcp.embedder import Qwen3EmbedBackend

        mock_backend = MagicMock(spec=Qwen3EmbedBackend)
        mock_backend.embed_single_query.return_value = [0.5, 0.6]
        mock_get.return_value = mock_backend

        res = await server._embed("hello", is_query=True)
        assert res == [0.5, 0.6]
        mock_backend.embed_single_query.assert_called_once()


async def test_embed_no_backend():
    """Line 325: backend is None."""
    with patch("wet_mcp.embedder.get_backend", return_value=None):
        res = await server._embed("test")
        assert res is None


async def test_embed_exception():
    """Lines 332-334: embedding raises exception."""
    with patch("wet_mcp.embedder.get_backend") as mock_get:
        mock_backend = MagicMock()
        mock_backend.embed_single.side_effect = Exception("embed error")
        mock_get.return_value = mock_backend

        res = await server._embed("test")
        assert res is None


# ---------------------------------------------------------------------------
# _embed_batch (lines 343, 346-348)
# ---------------------------------------------------------------------------


async def test_embed_batch_no_backend():
    """Line 343: backend is None."""
    with patch("wet_mcp.embedder.get_backend", return_value=None):
        res = await server._embed_batch(["test"])
        assert res is None


async def test_embed_batch_exception():
    """Lines 346-348: batch embedding raises exception."""
    with patch("wet_mcp.embedder.get_backend") as mock_get:
        mock_backend = MagicMock()
        mock_backend.embed_texts.side_effect = Exception("batch fail")
        mock_get.return_value = mock_backend

        res = await server._embed_batch(["test"])
        assert res is None


# ---------------------------------------------------------------------------
# _rerank_results (lines 377-380)
# ---------------------------------------------------------------------------


async def test_rerank_exception_fallback():
    """Lines 377-380: reranking raises, falls back to original order."""
    with patch("wet_mcp.reranker.get_reranker") as mock_get:
        mock_reranker = MagicMock()
        mock_reranker.rerank.side_effect = Exception("rerank fail")
        mock_get.return_value = mock_reranker

        results = [{"content": "a"}, {"content": "b"}, {"content": "c"}]
        res = await server._rerank_results("q", results, 2)
        assert len(res) == 2
        assert res[0]["content"] == "a"


async def test_rerank_fewer_results_than_top_n():
    """Line 363: results <= top_n, returns as-is."""
    with patch("wet_mcp.reranker.get_reranker") as mock_get:
        mock_get.return_value = MagicMock()

        results = [{"content": "a"}]
        res = await server._rerank_results("q", results, 5)
        assert len(res) == 1


# ---------------------------------------------------------------------------
# search tool: cache hit paths (lines 511, 535, 540)
# ---------------------------------------------------------------------------


async def test_search_cache_hit(_mock_web_cache):
    """Line 511: search returns cached result."""
    _mock_web_cache.get.return_value = "cached search result"
    result = await server.search("search", query="test")
    assert "cached search result" in result


async def test_research_cache_hit(_mock_web_cache):
    """Lines 539-540: research returns cached result."""
    _mock_web_cache.get.return_value = "cached research result"
    result = await server.search("research", query="test")
    assert "cached research result" in result


# ---------------------------------------------------------------------------
# search tool: SearXNG errors (lines 516-519)
# ---------------------------------------------------------------------------


async def test_search_searxng_timeout():
    """Lines 516-517: SearXNG startup timeout."""
    with patch(
        "wet_mcp.server.ensure_searxng",
        new_callable=AsyncMock,
        side_effect=TimeoutError,
    ):
        result = await server.search("search", query="test")
        assert "timed out" in result


async def test_search_searxng_startup_failed():
    """Lines 518-519: SearXNG startup exception."""
    with patch(
        "wet_mcp.server.ensure_searxng",
        new_callable=AsyncMock,
        side_effect=Exception("container died"),
    ):
        result = await server.search("search", query="test")
        assert "startup failed" in result


# ---------------------------------------------------------------------------
# search tool: missing query for research (line 535)
# ---------------------------------------------------------------------------


async def test_search_research_missing_query():
    """Line 535: research action requires query."""
    result = await server.search("research", query=None)
    assert "Error: query is required" in result


# ---------------------------------------------------------------------------
# search tool: docs missing library/query (lines 551, 553)
# ---------------------------------------------------------------------------


async def test_search_docs_missing_library():
    """Line 551: docs action requires library."""
    result = await server.search("docs", query="test")
    assert "library is required" in result


async def test_search_docs_missing_query():
    """Line 553: docs action requires query."""
    result = await server.search("docs", library="react")
    assert "query is required" in result


# ---------------------------------------------------------------------------
# extract tool: cache hit paths (lines 615, 636, 663)
# ---------------------------------------------------------------------------


async def test_extract_cache_hit(_mock_web_cache):
    """Line 615: extract returns cached result."""
    _mock_web_cache.get.return_value = "cached extract"
    result = await server.extract("extract", urls=["http://x.com"])
    assert "cached extract" in result


async def test_crawl_cache_hit(_mock_web_cache):
    """Line 636: crawl returns cached result."""
    _mock_web_cache.get.return_value = "cached crawl"
    result = await server.extract("crawl", urls=["http://x.com"])
    assert "cached crawl" in result


async def test_map_cache_hit(_mock_web_cache):
    """Line 663: map returns cached result."""
    _mock_web_cache.get.return_value = "cached map"
    result = await server.extract("map", urls=["http://x.com"])
    assert "cached map" in result


# ---------------------------------------------------------------------------
# config tool: sync_interval set, generic setattr (lines 885-888)
# ---------------------------------------------------------------------------


async def test_config_set_sync_interval():
    """Lines 885-886: set sync_interval via config."""
    result = await server.config("set", key="sync_interval", value="600")
    data = json.loads(result)
    assert data["status"] == "updated"
    assert data["key"] == "sync_interval"


async def test_config_set_generic_key():
    """Lines 887-888: set generic key (e.g. sync_remote) via setattr."""
    result = await server.config("set", key="sync_remote", value="s3://bucket")
    data = json.loads(result)
    assert data["status"] == "updated"
    assert data["key"] == "sync_remote"


# ---------------------------------------------------------------------------
# config tool: docs_reindex missing key, db not init (lines 906, 908)
# ---------------------------------------------------------------------------


async def test_config_docs_reindex_missing_key():
    """Line 906: docs_reindex without key."""
    result = await server.config("docs_reindex")
    data = json.loads(result)
    assert "error" in data
    assert "key" in data["error"]


async def test_config_docs_reindex_db_not_init():
    """Line 908: docs_reindex when docs DB is None."""
    server._docs_db = None
    result = await server.config("docs_reindex", key="react")
    data = json.loads(result)
    assert "error" in data
    assert "not initialized" in data["error"]


# ---------------------------------------------------------------------------
# _fetch_and_chunk_docs: llms.txt too small (line 1037)
# ---------------------------------------------------------------------------


async def test_fetch_and_chunk_docs_llms_txt_too_small():
    """Line 1037: llms.txt produces fewer chunks than _MIN_GH_CHUNKS."""
    with (
        patch("wet_mcp.sources.docs.try_llms_txt", new_callable=AsyncMock) as mock_llms,
        patch("wet_mcp.sources.docs.chunk_llms_txt") as mock_chunk_llms,
        patch(
            "wet_mcp.sources.docs._try_github_raw_docs", new_callable=AsyncMock
        ) as mock_gh,
        patch("wet_mcp.sources.docs.chunk_markdown") as mock_chunk_md,
        patch(
            "wet_mcp.sources.docs.fetch_docs_pages", new_callable=AsyncMock
        ) as mock_fetch,
    ):
        # llms.txt returns content but only 5 chunks (below _MIN_GH_CHUNKS=20)
        mock_llms.return_value = "some llms content"
        mock_chunk_llms.return_value = [{"content": f"c{i}"} for i in range(5)]
        # GitHub raw returns nothing
        mock_gh.return_value = []
        # Crawl returns enough
        mock_fetch.return_value = [
            {"content": "page content", "url": "http://docs.example.com", "title": "T"}
        ]
        mock_chunk_md.return_value = [{"content": f"chunk{i}"} for i in range(25)]

        chunks, pages = await server._fetch_and_chunk_docs("http://docs.example.com")
        assert pages == 1
        assert len(chunks) == 25


# ---------------------------------------------------------------------------
# _fetch_and_chunk_docs: crawl produces chunks with page titles (1085-1092)
# ---------------------------------------------------------------------------


async def test_fetch_and_chunk_docs_crawl_with_page_titles():
    """Lines 1085-1092: crawl chunks inherit page title when missing."""
    with (
        patch(
            "wet_mcp.sources.docs.try_llms_txt",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch(
            "wet_mcp.sources.docs._try_github_raw_docs",
            new_callable=AsyncMock,
            return_value=[],
        ),
        patch(
            "wet_mcp.sources.docs.fetch_docs_pages", new_callable=AsyncMock
        ) as mock_fetch,
        patch("wet_mcp.sources.docs.chunk_markdown") as mock_chunk,
    ):
        mock_fetch.return_value = [
            {"content": "page1", "url": "http://example.com/a", "title": "Page A"},
            {"content": "page2", "url": "http://example.com/b", "title": "Page B"},
        ]
        # Chunks without titles
        mock_chunk.side_effect = [
            [{"content": "chunk1"}, {"content": "chunk2", "title": ""}],
            [{"content": "chunk3", "title": "Existing"}],
        ]

        chunks, pages = await server._fetch_and_chunk_docs("http://example.com")
        assert pages == 2
        # chunk1 gets page title, chunk2 has empty title -> gets page title,
        # chunk3 has existing title -> keeps it
        assert chunks[0]["title"] == "Page A"
        assert chunks[1]["title"] == "Page A"
        assert chunks[2]["title"] == "Existing"


# ---------------------------------------------------------------------------
# _fetch_and_chunk_docs: README fallback (lines 1109-1121)
# ---------------------------------------------------------------------------


async def test_fetch_and_chunk_docs_readme_fallback():
    """Lines 1109-1118: all tiers fail, README fallback used."""
    with (
        patch(
            "wet_mcp.sources.docs.try_llms_txt",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch(
            "wet_mcp.sources.docs._try_github_raw_docs",
            new_callable=AsyncMock,
            return_value=[],
        ),
        patch(
            "wet_mcp.sources.docs.fetch_docs_pages",
            new_callable=AsyncMock,
            return_value=[],
        ),
        patch("wet_mcp.sources.docs.chunk_markdown", return_value=[]),
        patch(
            "wet_mcp.sources.docs._fetch_github_readme", new_callable=AsyncMock
        ) as mock_readme,
    ):
        mock_readme.return_value = [{"content": "readme chunk"}]
        chunks, pages = await server._fetch_and_chunk_docs(
            "http://example.com", repo_url="http://github.com/org/repo"
        )
        assert pages == 1
        assert chunks[0]["content"] == "readme chunk"


async def test_fetch_and_chunk_docs_all_tiers_fail_no_readme():
    """Lines 1109-1121: all tiers fail, README also empty."""
    with (
        patch(
            "wet_mcp.sources.docs.try_llms_txt",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch(
            "wet_mcp.sources.docs._try_github_raw_docs",
            new_callable=AsyncMock,
            return_value=[],
        ),
        patch(
            "wet_mcp.sources.docs.fetch_docs_pages",
            new_callable=AsyncMock,
            return_value=[],
        ),
        patch("wet_mcp.sources.docs.chunk_markdown", return_value=[]),
        patch(
            "wet_mcp.sources.docs._fetch_github_readme",
            new_callable=AsyncMock,
            return_value=None,
        ),
    ):
        chunks, pages = await server._fetch_and_chunk_docs("http://example.com")
        assert chunks == []
        assert pages == 0


# ---------------------------------------------------------------------------
# _background_index_and_search (lines 1160-1163, 1185-1207, 1218-1249, 1254)
# ---------------------------------------------------------------------------


async def test_background_index_fetch_timeout():
    """Lines 1160-1163: fetch times out in background indexer."""
    server._docs_db = MagicMock()
    server._docs_db.mark_version_indexed = MagicMock()
    server._docs_db.add_chunks = MagicMock()

    with (
        patch("wet_mcp.sources.docs._normalize_docs_url", return_value="http://docs.x"),
        patch(
            "wet_mcp.server._fetch_and_chunk_docs",
            new_callable=AsyncMock,
            side_effect=TimeoutError,
        ),
        patch(
            "wet_mcp.server.ensure_searxng",
            new_callable=AsyncMock,
            return_value="http://searxng",
        ),
        patch(
            "wet_mcp.server.searxng_search",
            new_callable=AsyncMock,
            return_value=json.dumps({"results": []}),
        ),
    ):
        await server._background_index_and_search(
            library="testlib",
            lib_key="testlib",
            language=None,
            docs_url="http://docs.x",
            repo_url="",
            query="test",
            version=None,
            lib_id="1",
            ver_id="1",
        )
        # No chunks -> returns early, no add_chunks call
        server._docs_db.add_chunks.assert_not_called()


async def test_background_index_with_fallback_alt_url():
    """Lines 1185-1207: fallback SearXNG finds alt URL with better content."""
    server._docs_db = MagicMock()

    fetch_call_count = 0

    async def fake_fetch(docs_url="", repo_url="", query="", library_hint=""):
        nonlocal fetch_call_count
        fetch_call_count += 1
        if fetch_call_count == 1:
            # First fetch: few results
            return [{"content": "c1"}], 1
        # Alt URL: more results
        return [{"content": f"c{i}"} for i in range(30)], 5

    with (
        patch(
            "wet_mcp.sources.docs._normalize_docs_url",
            return_value="http://original.com/docs",
        ),
        patch(
            "wet_mcp.server._fetch_and_chunk_docs",
            new_callable=AsyncMock,
            side_effect=fake_fetch,
        ),
        patch(
            "wet_mcp.server.ensure_searxng",
            new_callable=AsyncMock,
            return_value="http://searxng",
        ),
        patch(
            "wet_mcp.server.searxng_search",
            new_callable=AsyncMock,
            return_value=json.dumps(
                {"results": [{"url": "http://alt-docs.com/guide"}]}
            ),
        ),
        patch("wet_mcp.server._embed_batch", new_callable=AsyncMock, return_value=None),
    ):
        await server._background_index_and_search(
            library="testlib",
            lib_key="testlib",
            language=None,
            docs_url="http://original.com/docs",
            repo_url="",
            query="test",
            version=None,
            lib_id="1",
            ver_id="1",
        )
        server._docs_db.add_chunks.assert_called_once()
        # Alt URL was used (30 chunks > 1 chunk)
        args = server._docs_db.add_chunks.call_args
        assert len(args.kwargs.get("chunks", args[1].get("chunks", []))) == 30


async def test_background_index_with_embeddings():
    """Lines 1218-1249: generate embeddings for chunks."""
    server._docs_db = MagicMock()

    with (
        patch("wet_mcp.sources.docs._normalize_docs_url", return_value="http://docs.x"),
        patch(
            "wet_mcp.server._fetch_and_chunk_docs",
            new_callable=AsyncMock,
            return_value=(
                [
                    {"content": "chunk1", "title": "T1", "heading_path": "H1"},
                    {"content": "chunk2", "title": "T2"},
                    {"content": "chunk3"},
                ],
                3,
            ),
        ),
        patch(
            "wet_mcp.server.ensure_searxng",
            new_callable=AsyncMock,
            side_effect=Exception("no searxng"),
        ),
        patch("wet_mcp.embedder.get_backend") as mock_get_backend,
        patch("wet_mcp.server._embed_batch", new_callable=AsyncMock) as mock_embed,
    ):
        mock_get_backend.return_value = MagicMock()  # backend available
        mock_embed.return_value = [[0.1], [0.2], [0.3]]

        await server._background_index_and_search(
            library="testlib",
            lib_key="testlib",
            language=None,
            docs_url="http://docs.x",
            repo_url="",
            query="test",
            version=None,
            lib_id="1",
            ver_id="1",
        )
        server._docs_db.add_chunks.assert_called_once()
        call_kwargs = server._docs_db.add_chunks.call_args
        # Embeddings should be passed
        embs = call_kwargs.kwargs.get("embeddings") or call_kwargs[1].get("embeddings")
        assert embs == [[0.1], [0.2], [0.3]]
        server._docs_db.mark_version_indexed.assert_called_once()


async def test_background_index_exception():
    """Line 1254: top-level exception in background indexer."""
    server._docs_db = MagicMock()

    with patch(
        "wet_mcp.sources.docs._normalize_docs_url",
        side_effect=Exception("unexpected"),
    ):
        # Should not raise
        await server._background_index_and_search(
            library="testlib",
            lib_key="testlib",
            language=None,
            docs_url="http://docs.x",
            repo_url="",
            query="test",
            version=None,
            lib_id="1",
            ver_id="1",
        )


async def test_background_index_with_language_fallback():
    """Lines 1166-1171: fallback query includes language when provided."""
    server._docs_db = MagicMock()

    with (
        patch("wet_mcp.sources.docs._normalize_docs_url", return_value="http://docs.x"),
        patch(
            "wet_mcp.server._fetch_and_chunk_docs",
            new_callable=AsyncMock,
            return_value=([{"content": "c1"}], 1),
        ),
        patch(
            "wet_mcp.server.ensure_searxng",
            new_callable=AsyncMock,
            return_value="http://searxng",
        ),
        patch("wet_mcp.server.searxng_search", new_callable=AsyncMock) as mock_search,
        patch("wet_mcp.server._embed_batch", new_callable=AsyncMock, return_value=None),
    ):
        mock_search.return_value = json.dumps({"results": []})

        await server._background_index_and_search(
            library="redis",
            lib_key="redis:python",
            language="python",
            docs_url="http://docs.x",
            repo_url="",
            query="test",
            version=None,
            lib_id="1",
            ver_id="1",
        )
        # Verify fallback query includes language
        call_args = mock_search.call_args
        assert "python" in call_args.kwargs["request"].query


async def test_background_index_embed_timeout():
    """Lines 1238-1239: embedding batch times out."""
    server._docs_db = MagicMock()

    with (
        patch("wet_mcp.sources.docs._normalize_docs_url", return_value="http://docs.x"),
        patch(
            "wet_mcp.server._fetch_and_chunk_docs",
            new_callable=AsyncMock,
            return_value=([{"content": "c1"}], 1),
        ),
        patch(
            "wet_mcp.server.ensure_searxng",
            new_callable=AsyncMock,
            side_effect=Exception("no"),
        ),
        patch("wet_mcp.embedder.get_backend") as mock_get_backend,
        patch(
            "wet_mcp.server._embed_batch",
            new_callable=AsyncMock,
            side_effect=TimeoutError,
        ),
    ):
        mock_get_backend.return_value = MagicMock()

        await server._background_index_and_search(
            library="testlib",
            lib_key="testlib",
            language=None,
            docs_url="http://docs.x",
            repo_url="",
            query="test",
            version=None,
            lib_id="1",
            ver_id="1",
        )
        # Should still add chunks with embeddings=None
        server._docs_db.add_chunks.assert_called_once()


# ---------------------------------------------------------------------------
# _search_cached_index (line 1289, 1304)
# ---------------------------------------------------------------------------


async def test_search_cached_index_no_results():
    """Line 1304: search returns empty results -> None."""
    server._docs_db.get_library.return_value = {
        "id": 1,
        "discovery_version": 999,
    }
    server._docs_db.get_best_version.return_value = {
        "id": 1,
        "chunk_count": 10,
        "version": "latest",
    }
    server._docs_db.search.return_value = []

    with patch("wet_mcp.server._embed", new_callable=AsyncMock, return_value=None):
        result = await server._search_cached_index("lib", "query", None, 10)
        assert result is None


async def test_search_cached_index_version_zero_chunks():
    """Line 1289: version has chunk_count=0 -> None."""
    server._docs_db.get_library.return_value = {
        "id": 1,
        "discovery_version": 999,
    }
    server._docs_db.get_best_version.return_value = {
        "id": 1,
        "chunk_count": 0,
        "version": "latest",
    }

    result = await server._search_cached_index("lib", "query", None, 10)
    assert result is None


# ---------------------------------------------------------------------------
# _discover_docs_url: SearXNG fallback paths (lines 1390-1391)
# ---------------------------------------------------------------------------


async def test_discover_docs_url_searxng_timeout():
    """Lines 1388-1389: SearXNG fallback times out."""
    with (
        patch(
            "wet_mcp.sources.docs.discover_library",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch(
            "wet_mcp.server.ensure_searxng",
            new_callable=AsyncMock,
            side_effect=TimeoutError,
        ),
    ):
        docs_url, repo_url, registry, desc = await server._discover_docs_url(
            "mylib", None
        )
        assert docs_url == ""


async def test_discover_docs_url_searxng_json_decode_error():
    """Lines 1390-1391: SearXNG returns invalid JSON."""
    with (
        patch(
            "wet_mcp.sources.docs.discover_library",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch(
            "wet_mcp.server.ensure_searxng",
            new_callable=AsyncMock,
            return_value="http://searxng",
        ),
        patch(
            "wet_mcp.server.searxng_search",
            new_callable=AsyncMock,
            return_value="not json",
        ),
    ):
        docs_url, repo_url, registry, desc = await server._discover_docs_url(
            "mylib", None
        )
        assert docs_url == ""


async def test_discover_docs_url_with_language():
    """Lines 1366-1368: language included in search query."""
    with (
        patch(
            "wet_mcp.sources.docs.discover_library",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch(
            "wet_mcp.server.ensure_searxng",
            new_callable=AsyncMock,
            return_value="http://searxng",
        ),
        patch("wet_mcp.server.searxng_search", new_callable=AsyncMock) as mock_search,
    ):
        mock_search.return_value = json.dumps(
            {"results": [{"url": "http://docs.redis.io"}]}
        )
        docs_url, _, _, _ = await server._discover_docs_url("redis", "python")
        assert docs_url == "http://docs.redis.io"
        # Verify language was in the query
        call_args = mock_search.call_args
        assert "python" in call_args.kwargs["request"].query


# ---------------------------------------------------------------------------
# __main__ guard (line 1542)
# ---------------------------------------------------------------------------


def test_main_entry_point():
    """Line 1542: main() calls mcp.run()."""
    with patch("wet_mcp.server.mcp.run") as mock_run:
        server.main()
        mock_run.assert_called_once()


# ---------------------------------------------------------------------------
# media tool: download with security check
# ---------------------------------------------------------------------------


async def test_media_download_invalid_output_dir(_mock_settings):
    """Lines 726-730: output_dir outside configured download_dir."""
    _mock_settings.download_dir = "/tmp/downloads"
    result = await server.media(
        "download", media_urls=["http://x.com/img.jpg"], output_dir="/etc/malicious"
    )
    assert "Security Alert" in result


async def test_media_download_missing_urls():
    """Line 718: download without media_urls."""
    result = await server.media("download")
    assert "media_urls is required" in result


async def test_media_list_missing_url():
    """Line 710: list without url."""
    result = await server.media("list")
    assert "url is required" in result


async def test_media_analyze_missing_url():
    """Line 742: analyze without url."""
    result = await server.media("analyze")
    assert "url" in result and "required" in result


async def test_media_invalid_action():
    """Line 752: unknown media action."""
    result = await server.media("invalid")
    assert "Unknown action" in result


# ---------------------------------------------------------------------------
# _do_research: reranking results filtering
# ---------------------------------------------------------------------------


async def test_do_research_reranking_filters_low_scores():
    """Lines 960-963: reranking filters results with score <= 0.3."""
    with (
        patch(
            "wet_mcp.server.ensure_searxng",
            new_callable=AsyncMock,
            return_value="http://searxng",
        ),
        patch("wet_mcp.server.searxng_search", new_callable=AsyncMock) as mock_search,
        patch("wet_mcp.server._rerank_results", new_callable=AsyncMock) as mock_rerank,
    ):
        mock_search.return_value = json.dumps(
            {
                "results": [
                    {"url": "http://arxiv.org/1", "content": "good"},
                    {"url": "http://other.org/2", "content": "bad"},
                ]
            }
        )
        # Only first result has score > 0.3
        mock_rerank.return_value = [
            {"url": "http://arxiv.org/1", "content": "good", "score": 0.8},
            {"url": "http://other.org/2", "content": "bad", "score": 0.1},
        ]
        result = await server._do_research("test query")
        data = json.loads(result)
        # Low-score result filtered
        assert len(data["results"]) == 1
        assert data["results"][0]["source_type"] == "arxiv"


# ---------------------------------------------------------------------------
# _do_research: reranking exception path
# ---------------------------------------------------------------------------


async def test_do_research_rerank_exception():
    """Lines 964-965: reranking exception logged, original results kept."""
    with (
        patch(
            "wet_mcp.server.ensure_searxng",
            new_callable=AsyncMock,
            return_value="http://searxng",
        ),
        patch("wet_mcp.server.searxng_search", new_callable=AsyncMock) as mock_search,
        patch(
            "wet_mcp.server._rerank_results",
            new_callable=AsyncMock,
            side_effect=Exception("rerank boom"),
        ),
    ):
        mock_search.return_value = json.dumps(
            {"results": [{"url": "http://example.org", "content": "result"}]}
        )
        result = await server._do_research("test query")
        # Should still return results (reranking is best-effort)
        data = json.loads(result)
        assert len(data["results"]) >= 1


# ---------------------------------------------------------------------------
# _background_index_and_search: fallback alt URL timeout
# ---------------------------------------------------------------------------


async def test_background_index_alt_url_fetch_timeout():
    """Lines 1201-1202: alt URL fetch times out, continues."""
    server._docs_db = MagicMock()

    with (
        patch("wet_mcp.sources.docs._normalize_docs_url", return_value="http://docs.x"),
        patch(
            "wet_mcp.server._fetch_and_chunk_docs", new_callable=AsyncMock
        ) as mock_fetch,
        patch(
            "wet_mcp.server.ensure_searxng",
            new_callable=AsyncMock,
            return_value="http://searxng",
        ),
        patch(
            "wet_mcp.server.searxng_search",
            new_callable=AsyncMock,
            return_value=json.dumps(
                {"results": [{"url": "http://alt-docs.com/guide"}]}
            ),
        ),
        patch("wet_mcp.server._embed_batch", new_callable=AsyncMock, return_value=None),
    ):
        # First fetch returns few chunks, alt URL fetch times out
        mock_fetch.side_effect = [
            ([{"content": "c1"}], 1),
            TimeoutError("alt timeout"),
        ]

        await server._background_index_and_search(
            library="testlib",
            lib_key="testlib",
            language=None,
            docs_url="http://docs.x",
            repo_url="",
            query="test",
            version=None,
            lib_id="1",
            ver_id="1",
        )
        # Still uses original chunks
        server._docs_db.add_chunks.assert_called_once()


# ---------------------------------------------------------------------------
# _background_index_and_search: skip same-netloc alt URLs
# ---------------------------------------------------------------------------


async def test_background_index_skip_same_netloc():
    """Lines 1192-1195: skip alt URL with same netloc as original."""
    server._docs_db = MagicMock()

    with (
        patch(
            "wet_mcp.sources.docs._normalize_docs_url",
            return_value="http://docs.x/guide",
        ),
        patch(
            "wet_mcp.server._fetch_and_chunk_docs",
            new_callable=AsyncMock,
            return_value=([{"content": "c1"}], 1),
        ),
        patch(
            "wet_mcp.server.ensure_searxng",
            new_callable=AsyncMock,
            return_value="http://searxng",
        ),
        patch(
            "wet_mcp.server.searxng_search",
            new_callable=AsyncMock,
            return_value=json.dumps({"results": [{"url": "http://docs.x/other-page"}]}),
        ),
        patch("wet_mcp.server._embed_batch", new_callable=AsyncMock, return_value=None),
    ):
        await server._background_index_and_search(
            library="testlib",
            lib_key="testlib",
            language=None,
            docs_url="http://docs.x/guide",
            repo_url="",
            query="test",
            version=None,
            lib_id="1",
            ver_id="1",
        )
        # Original chunks used (same netloc alt URL skipped)
        server._docs_db.add_chunks.assert_called_once()
        args = server._docs_db.add_chunks.call_args
        chunks = args.kwargs.get("chunks") or args[1].get("chunks")
        assert len(chunks) == 1
