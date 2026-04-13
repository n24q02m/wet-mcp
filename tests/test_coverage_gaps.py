"""Tests to cover remaining gaps in sync.py, setup_tool.py, cache.py, and reranker.py."""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# sync.py coverage gaps
# ---------------------------------------------------------------------------


class TestSyncFullEmptyJsonl:
    """Cover sync_full: empty remote JSONL branch."""

    @pytest.mark.asyncio
    @patch("wet_mcp.sync._has_token_available", return_value=True)
    @patch("wet_mcp.sync._get_valid_token")
    @patch("wet_mcp.sync.settings")
    @patch("wet_mcp.sync.sync_pull")
    @patch("wet_mcp.sync.sync_push")
    @patch("wet_mcp.db.DocsDB")
    async def test_empty_remote_jsonl(
        self,
        mock_DocsDB,
        mock_push,
        mock_pull,
        mock_valid_token,
        mock_settings,
        _mock_token,
    ):
        from wet_mcp.sync import sync_full

        mock_settings.sync_enabled = True
        mock_settings.google_drive_client_id = "client123"
        mock_settings.sync_folder = "folder"
        mock_settings.get_db_path.return_value = Path("/db/db.sqlite")

        mock_valid_token.return_value = {"access_token": "t"}
        mock_pull.return_value = Path("/tmp/remote.sqlite")
        mock_push.return_value = True

        # Remote DB returns empty JSONL
        mock_remote_db = MagicMock()
        mock_remote_db.export_jsonl.return_value = "   "  # whitespace only
        mock_DocsDB.return_value = mock_remote_db

        mock_local_db = MagicMock()
        result = await sync_full(mock_local_db)

        assert result["status"] == "ok"
        assert result["pull"]["libraries"] == 0
        assert result["pull"]["chunks"] == 0


class TestAutoSyncLoopError:
    """Cover auto_sync_loop normal iteration + error handling."""

    @pytest.mark.asyncio
    @patch("wet_mcp.sync.settings")
    @patch("wet_mcp.sync.sync_full")
    async def test_auto_sync_loop_handles_error(self, mock_sync, mock_settings):
        from wet_mcp.sync import _auto_sync_loop

        mock_settings.sync_interval = 1

        call_count = 0

        async def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("Sync error")
            # Second call: cancel the task
            raise asyncio.CancelledError()

        mock_sync.side_effect = side_effect

        with patch("wet_mcp.sync.asyncio.sleep", new_callable=AsyncMock):
            await _auto_sync_loop(MagicMock())

        assert call_count == 2

    @pytest.mark.asyncio
    @patch("wet_mcp.sync.settings")
    @patch("wet_mcp.sync.sync_full")
    async def test_auto_sync_loop_runs_sync(self, mock_sync, mock_settings):
        """Successful sync_full call in loop."""
        from wet_mcp.sync import _auto_sync_loop

        mock_settings.sync_interval = 1

        call_count = 0

        async def sync_side_effect(db):
            nonlocal call_count
            call_count += 1
            if call_count >= 1:
                raise asyncio.CancelledError()
            return {"status": "ok"}

        mock_sync.side_effect = sync_side_effect

        with patch("wet_mcp.sync.asyncio.sleep", new_callable=AsyncMock):
            await _auto_sync_loop(MagicMock())

        assert mock_sync.call_count == 1


class TestStartAutoSyncDisabled:
    """Cover start_auto_sync returns when interval <= 0."""

    @patch("wet_mcp.sync.settings")
    @patch("wet_mcp.sync.asyncio.create_task")
    def test_disabled_by_sync_interval_zero(self, mock_create, mock_settings):
        import wet_mcp.sync
        from wet_mcp.sync import start_auto_sync

        mock_settings.sync_enabled = True
        mock_settings.sync_interval = 0
        wet_mcp.sync._sync_task = None

        start_auto_sync(MagicMock())
        mock_create.assert_not_called()

    @patch("wet_mcp.sync.settings")
    @patch("wet_mcp.sync.asyncio.create_task")
    def test_disabled_by_sync_enabled_false(self, mock_create, mock_settings):
        import wet_mcp.sync
        from wet_mcp.sync import start_auto_sync

        mock_settings.sync_enabled = False
        mock_settings.sync_interval = 60
        wet_mcp.sync._sync_task = None

        start_auto_sync(MagicMock())
        mock_create.assert_not_called()


class TestSyncFullNoClientId:
    """Cover sync_full when client ID is not set."""

    @pytest.mark.asyncio
    @patch("wet_mcp.sync.settings")
    async def test_sync_full_no_client_id(self, mock_settings):
        from wet_mcp.sync import sync_full

        mock_settings.sync_enabled = True
        mock_settings.google_drive_client_id = ""

        result = await sync_full(MagicMock())
        assert result["status"] == "error"
        assert "GOOGLE_DRIVE_CLIENT_ID" in result["message"]


class TestSetupSyncNoClientId:
    """Cover setup_sync when no GOOGLE_DRIVE_CLIENT_ID is set."""

    @patch("wet_mcp.sync.settings")
    def test_setup_sync_no_client_id(self, mock_settings):
        from wet_mcp.sync import setup_sync

        mock_settings.google_drive_client_id = ""

        with pytest.raises(SystemExit):
            setup_sync()


# ---------------------------------------------------------------------------
# setup_tool.py coverage gaps (migrated from __main__.py)
# ---------------------------------------------------------------------------


class TestSetupToolCoverageGaps:
    """Cover setup_tool.py edge cases for local embedding/reranker."""

    @patch("qwen3_embed.TextEmbedding")
    def test_local_embedding_empty_result(self, mock_te):
        """embed returns empty list -- returns warning dict."""
        from wet_mcp.setup_tool import _download_local_embedding

        mock_settings = MagicMock()
        mock_settings.resolve_local_embedding_model.return_value = "org/embed"

        mock_model = MagicMock()
        mock_model.embed.return_value = iter([])
        mock_te.return_value = mock_model

        result = _download_local_embedding(mock_settings)
        assert result["status"] == "warning"

    @patch("wet_mcp.setup_tool.clear_model_cache")
    @patch("qwen3_embed.TextEmbedding")
    def test_local_embedding_empty_after_retry(self, mock_te, mock_clear):
        """embed returns empty after cache clear retry."""
        from wet_mcp.setup_tool import _download_local_embedding

        mock_settings = MagicMock()
        mock_settings.resolve_local_embedding_model.return_value = "org/embed"

        exc = Exception("NO_SUCHFILE: file doesn't exist")
        mock_model_retry = MagicMock()
        mock_model_retry.embed.return_value = iter([])
        mock_te.side_effect = [exc, mock_model_retry]

        result = _download_local_embedding(mock_settings)

        mock_clear.assert_called_once_with("org/embed")
        assert result["status"] == "warning"

    @patch("wet_mcp.setup_tool._EMBEDDING_CANDIDATES", ["gemini/embed"])
    @patch("wet_mcp.reranker.init_reranker")
    @patch("wet_mcp.embedder.init_backend")
    def test_cloud_reranker_init_exception(self, mock_init, mock_rr_init):
        """reranker init raises exception, caught by except."""
        from wet_mcp.setup_tool import _validate_cloud_models

        mock_settings = MagicMock()
        mock_settings.resolve_embedding_model.return_value = None
        mock_settings.resolve_rerank_model.return_value = "cohere/rerank"

        mock_backend = MagicMock()
        mock_backend.check_available.return_value = 768
        mock_init.return_value = mock_backend

        mock_rr_init.side_effect = Exception("reranker init failed")

        result = _validate_cloud_models(mock_settings)
        assert result["cloud_ready"] is True
        assert result["reranker"] is None

    @patch("qwen3_embed.TextCrossEncoder")
    def test_local_reranker_empty_result(self, mock_tce):
        """local reranker returns empty scores."""
        from wet_mcp.setup_tool import _download_local_reranker

        mock_settings = MagicMock()
        mock_settings.rerank_enabled = True
        mock_settings.resolve_local_rerank_model.return_value = "org/rerank"

        mock_reranker = MagicMock()
        mock_reranker.rerank.return_value = iter([])
        mock_tce.return_value = mock_reranker

        result = _download_local_reranker(mock_settings)
        assert result["status"] == "warning"

    @patch("wet_mcp.setup_tool.clear_model_cache")
    @patch("qwen3_embed.TextCrossEncoder")
    def test_local_reranker_empty_after_retry(self, mock_tce, mock_clear):
        """reranker retry returns empty scores."""
        from wet_mcp.setup_tool import _download_local_reranker

        mock_settings = MagicMock()
        mock_settings.rerank_enabled = True
        mock_settings.resolve_local_rerank_model.return_value = "org/rerank"

        exc = Exception("NO_SUCHFILE: file doesn't exist")
        mock_reranker_retry = MagicMock()
        mock_reranker_retry.rerank.return_value = iter([])
        mock_tce.side_effect = [exc, mock_reranker_retry]

        result = _download_local_reranker(mock_settings)

        mock_clear.assert_called_once_with("org/rerank")
        assert result["status"] == "warning"

    @patch("qwen3_embed.TextCrossEncoder")
    def test_local_reranker_non_cache_error_reraises(self, mock_tce):
        """non-cache reranker error is re-raised."""
        from wet_mcp.setup_tool import _download_local_reranker

        mock_settings = MagicMock()
        mock_settings.rerank_enabled = True
        mock_settings.resolve_local_rerank_model.return_value = "org/rerank"

        mock_tce.side_effect = ImportError("qwen3_embed broken")

        with pytest.raises(ImportError, match="broken"):
            _download_local_reranker(mock_settings)


# ---------------------------------------------------------------------------
# cache.py coverage gaps
# ---------------------------------------------------------------------------


class TestCachePurgeAndClose:
    """Cover cache.py L119-120 (periodic purge) and L190-191 (close exception)."""

    def test_periodic_purge_triggered(self, tmp_path):
        """L119-120: _purge_expired called after _PURGE_INTERVAL ops."""
        from wet_mcp import cache as cache_mod
        from wet_mcp.cache import WebCache

        c = WebCache(tmp_path / "test.db")

        # Set op_count to just below threshold
        c._op_count = cache_mod._PURGE_INTERVAL - 1

        # This set should trigger purge
        c.set("search", {"q": "test"}, "content")

        # After purge, op_count resets to 0
        assert c._op_count == 0
        c.close()

    def test_close_handles_exception(self):
        """L190-191: close() catches exceptions from conn.close()."""
        from wet_mcp.cache import WebCache

        cache = WebCache.__new__(WebCache)
        cache._conn = MagicMock()
        cache._conn.close.side_effect = Exception("already closed")

        cache.close()  # Should not raise


# ---------------------------------------------------------------------------
# reranker.py coverage gaps
# ---------------------------------------------------------------------------


class TestCohereRerankerResults:
    """Cover CohereReranker rerank result parsing."""

    def test_rerank_with_object_results(self):
        from wet_mcp.reranker import CohereReranker

        reranker = CohereReranker(api_key="test-key")

        mock_response = MagicMock()
        item0 = MagicMock()
        item0.index = 0
        item0.relevance_score = 0.8
        item1 = MagicMock()
        item1.index = 1
        item1.relevance_score = 0.95
        mock_response.results = [item0, item1]

        mock_client = MagicMock()
        mock_client.rerank.return_value = mock_response

        with patch.object(reranker, "_get_client", return_value=mock_client):
            results = reranker.rerank("query", ["doc1", "doc2"], top_n=2)

        assert results == [(1, 0.95), (0, 0.8)]


class TestSetupPatchSearxngVersion:
    """Cover setup.py patch_searxng_version() gaps."""

    @patch("wet_mcp.setup._find_searx_package_dir")
    def test_patch_searxng_version_success(self, mock_find_dir):
        from wet_mcp.setup import patch_searxng_version

        mock_dir = MagicMock(spec=Path)
        mock_find_dir.return_value = mock_dir
        mock_file = MagicMock(spec=Path)
        mock_dir.__truediv__.return_value = mock_file
        mock_file.exists.return_value = False

        patch_searxng_version()

        mock_file.write_text.assert_called_once()
        args = mock_file.write_text.call_args[0][0]
        assert "VERSION_STRING =" in args

    @patch("wet_mcp.setup._find_searx_package_dir")
    def test_patch_searxng_version_already_exists(self, mock_find_dir):
        from wet_mcp.setup import patch_searxng_version

        mock_dir = MagicMock(spec=Path)
        mock_find_dir.return_value = mock_dir
        mock_file = MagicMock(spec=Path)
        mock_dir.__truediv__.return_value = mock_file
        mock_file.exists.return_value = True

        patch_searxng_version()

        mock_file.write_text.assert_not_called()

    @patch("wet_mcp.setup._find_searx_package_dir")
    def test_patch_searxng_version_no_dir(self, mock_find_dir):
        from wet_mcp.setup import patch_searxng_version

        mock_find_dir.return_value = None
        patch_searxng_version()
        # No error should be raised

    @patch("wet_mcp.setup._find_searx_package_dir", side_effect=Exception("Test error"))
    @patch("wet_mcp.setup.logger.warning")
    def test_patch_searxng_version_exception(self, mock_warning, mock_find_dir):
        from wet_mcp.setup import patch_searxng_version

        patch_searxng_version()
        mock_warning.assert_called_once()
