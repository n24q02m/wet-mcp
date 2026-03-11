"""Tests to cover remaining gaps in sync.py, __main__.py, cache.py, and reranker.py."""

import asyncio
import subprocess
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest

# ---------------------------------------------------------------------------
# sync.py coverage gaps
# ---------------------------------------------------------------------------


class TestDownloadRcloneBinaryNotFound:
    """Cover sync.py L147-148: rclone binary not found in archive (for-else)."""

    @pytest.mark.asyncio
    @patch("wet_mcp.sync._get_rclone_dir")
    @patch("wet_mcp.sync._get_platform_info")
    @patch.object(Path, "exists")
    @patch("wet_mcp.sync.httpx.AsyncClient")
    @patch("wet_mcp.sync.tempfile.NamedTemporaryFile")
    @patch("wet_mcp.sync.zipfile.ZipFile")
    @patch.object(Path, "mkdir")
    async def test_binary_not_in_archive(
        self,
        mock_mkdir,
        mock_zip,
        mock_temp,
        mock_client,
        mock_exists,
        mock_info,
        mock_dir,
    ):
        from wet_mcp.sync import _download_rclone

        mock_info.return_value = ("linux", "amd64", "")
        mock_dir.return_value = Path("/mock/dir")
        mock_exists.return_value = False

        # Mock httpx response
        mock_resp = MagicMock()
        mock_resp.content = b"zip_content"
        mock_client_instance = AsyncMock()
        mock_client_instance.get = AsyncMock(return_value=mock_resp)
        mock_client.return_value.__aenter__ = AsyncMock(
            return_value=mock_client_instance
        )
        mock_client.return_value.__aexit__ = AsyncMock(return_value=None)

        # Setup tempfile
        mock_tmp = MagicMock()
        mock_tmp.name = "/tmp/fake.zip"
        mock_temp.return_value.__enter__.return_value = mock_tmp

        # Setup zipfile with NO matching binary (triggers for-else)
        mock_zf = MagicMock()
        mock_info_entry = MagicMock()
        mock_info_entry.filename = "rclone-v1.68.2-linux-amd64/README.md"
        mock_info_entry.is_dir.return_value = False
        mock_zf.infolist.return_value = [mock_info_entry]
        mock_zip.return_value.__enter__.return_value = mock_zf

        result = await _download_rclone()
        assert result is None


class TestSyncFullEmptyJsonl:
    """Cover sync.py L331: empty remote JSONL branch."""

    @pytest.mark.asyncio
    @patch("wet_mcp.sync._has_token_available", return_value=True)
    @patch("wet_mcp.sync.settings")
    @patch("wet_mcp.sync.ensure_rclone")
    @patch("wet_mcp.sync.check_remote_configured")
    @patch("wet_mcp.sync.sync_pull")
    @patch("wet_mcp.sync.sync_push")
    @patch("wet_mcp.db.DocsDB")
    async def test_empty_remote_jsonl(
        self,
        mock_DocsDB,
        mock_push,
        mock_pull,
        mock_check,
        mock_ensure,
        mock_settings,
        _mock_token,
    ):
        from wet_mcp.sync import sync_full

        mock_settings.sync_enabled = True
        mock_settings.sync_remote = "gdrive"
        mock_settings.sync_folder = "folder"
        mock_settings.get_db_path.return_value = Path("/db/db.sqlite")

        mock_ensure.return_value = Path("/rclone")
        mock_check.return_value = True
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
    """Cover sync.py L374, L378-379: auto_sync_loop normal iteration + error handling."""

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
        """Cover L374: successful sync_full call in loop."""
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
    """Cover sync.py L388: start_auto_sync returns when interval <= 0."""

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


class TestSetupSyncNoToken:
    """Cover sync.py L498-515: setup_sync manual setup path when token extraction fails."""

    @patch("wet_mcp.sync._get_rclone_path")
    @patch("wet_mcp.sync.subprocess.run")
    @patch("wet_mcp.sync._extract_token")
    def test_manual_setup_unix(self, mock_extract, mock_run, mock_get_path, capsys):
        from wet_mcp.sync import setup_sync

        mock_get_path.return_value = Path("/rclone")
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="some output"
        )
        mock_extract.return_value = None  # Token extraction fails

        with patch("wet_mcp.sync.sys.platform", "linux"):
            setup_sync("drive")

        captured = capsys.readouterr()
        assert "MANUAL SETUP" in captured.out
        assert "Could not auto-extract token" in captured.out
        assert "SYNC_ENABLED=true" in captured.out

    @patch("wet_mcp.sync._get_rclone_path")
    @patch("wet_mcp.sync.subprocess.run")
    @patch("wet_mcp.sync._extract_token")
    def test_manual_setup_windows(self, mock_extract, mock_run, mock_get_path, capsys):
        from wet_mcp.sync import setup_sync

        mock_get_path.return_value = Path("/rclone")
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="some output"
        )
        mock_extract.return_value = None

        with patch("wet_mcp.sync.sys.platform", "win32"):
            setup_sync("drive")

        captured = capsys.readouterr()
        assert "MANUAL SETUP" in captured.out
        assert "SYNC_ENABLED=true" in captured.out

    @patch("wet_mcp.sync._get_rclone_path")
    @patch("wet_mcp.sync.subprocess.run")
    @patch("wet_mcp.sync._extract_token")
    def test_non_drive_remote_name(self, mock_extract, mock_run, mock_get_path, capsys):
        """Non-drive remote type uses type name as remote name."""
        from wet_mcp.sync import setup_sync

        mock_get_path.return_value = Path("/rclone")
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="output"
        )
        mock_extract.return_value = None

        with patch("wet_mcp.sync.sys.platform", "linux"):
            setup_sync("s3")

        captured = capsys.readouterr()
        assert "MANUAL SETUP" in captured.out
        assert "SYNC_ENABLED=true" in captured.out


# ---------------------------------------------------------------------------
# __main__.py coverage gaps
# ---------------------------------------------------------------------------


class TestWarmupEmptyResults:
    """Cover __main__.py L108, L118: empty embedding results."""

    @patch("wet_mcp.setup.run_auto_setup")
    @patch("qwen3_embed.TextEmbedding")
    @patch("wet_mcp.config.settings")
    def test_local_embedding_empty_result(self, mock_settings, mock_te, mock_setup):
        """L108: embed returns empty list."""
        from wet_mcp.__main__ import _warmup

        mock_settings.setup_litellm.return_value = "local"
        mock_settings.resolve_local_embedding_model.return_value = "org/embed"
        mock_settings.rerank_enabled = False

        mock_model = MagicMock()
        mock_model.embed.return_value = iter([])  # empty
        mock_te.return_value = mock_model

        _warmup()  # Should print warning but not raise

    @patch("wet_mcp.setup.run_auto_setup")
    @patch("wet_mcp.__main__._clear_model_cache")
    @patch("qwen3_embed.TextEmbedding")
    @patch("wet_mcp.config.settings")
    def test_local_embedding_empty_after_retry(
        self, mock_settings, mock_te, mock_clear, mock_setup
    ):
        """L118: embed returns empty after cache clear retry."""
        from wet_mcp.__main__ import _warmup

        mock_settings.setup_litellm.return_value = "local"
        mock_settings.resolve_local_embedding_model.return_value = "org/embed"
        mock_settings.rerank_enabled = False

        # First call: cache error, second call: empty result
        exc = Exception("NO_SUCHFILE: file doesn't exist")
        mock_model_retry = MagicMock()
        mock_model_retry.embed.return_value = iter([])  # empty after retry
        mock_te.side_effect = [exc, mock_model_retry]

        _warmup()

        mock_clear.assert_called_once_with("org/embed")


class TestWarmupRerankerEdgeCases:
    """Cover __main__.py L87-88, L134, L144-146."""

    @patch("wet_mcp.setup.run_auto_setup")
    @patch("wet_mcp.server._EMBEDDING_CANDIDATES", ["gemini/embed"])
    @patch("wet_mcp.embedder.init_backend")
    @patch("wet_mcp.config.settings")
    def test_cloud_reranker_init_exception(self, mock_settings, mock_init, mock_setup):
        """L87-88: reranker init raises exception, caught by except."""
        from wet_mcp.__main__ import _warmup

        mock_settings.setup_litellm.return_value = "sdk"
        mock_settings.resolve_embedding_model.return_value = None
        mock_settings.resolve_rerank_model.return_value = "cohere/rerank"
        mock_settings.get_embedding_litellm_kwargs.return_value = {}
        mock_settings.get_rerank_litellm_kwargs.return_value = {}

        mock_backend = MagicMock()
        mock_backend.check_available.return_value = 768
        mock_init.return_value = mock_backend

        with patch("wet_mcp.reranker.init_reranker") as mock_rr_init:
            mock_rr_init.side_effect = Exception("reranker init failed")
            _warmup()  # Should print cloud embedding message, not raise

    @patch("wet_mcp.setup.run_auto_setup")
    @patch("qwen3_embed.TextCrossEncoder")
    @patch("qwen3_embed.TextEmbedding")
    @patch("wet_mcp.config.settings")
    def test_local_reranker_empty_result(
        self, mock_settings, mock_te, mock_tce, mock_setup
    ):
        """L134: local reranker returns empty scores."""
        from wet_mcp.__main__ import _warmup

        mock_settings.setup_litellm.return_value = "local"
        mock_settings.resolve_local_embedding_model.return_value = "org/embed"
        mock_settings.resolve_local_rerank_model.return_value = "org/rerank"
        mock_settings.rerank_enabled = True

        mock_embed = MagicMock()
        mock_embed.embed.return_value = iter([np.array([0.1])])
        mock_te.return_value = mock_embed

        mock_reranker = MagicMock()
        mock_reranker.rerank.return_value = iter([])  # empty scores
        mock_tce.return_value = mock_reranker

        _warmup()  # Should print warning but not raise

    @patch("wet_mcp.setup.run_auto_setup")
    @patch("wet_mcp.__main__._clear_model_cache")
    @patch("qwen3_embed.TextCrossEncoder")
    @patch("qwen3_embed.TextEmbedding")
    @patch("wet_mcp.config.settings")
    def test_local_reranker_empty_after_retry(
        self, mock_settings, mock_te, mock_tce, mock_clear, mock_setup
    ):
        """L144-146: reranker retry returns empty scores."""
        from wet_mcp.__main__ import _warmup

        mock_settings.setup_litellm.return_value = "local"
        mock_settings.resolve_local_embedding_model.return_value = "org/embed"
        mock_settings.resolve_local_rerank_model.return_value = "org/rerank"
        mock_settings.rerank_enabled = True

        mock_embed = MagicMock()
        mock_embed.embed.return_value = iter([np.array([0.1])])
        mock_te.return_value = mock_embed

        # First call: cache error, second call: empty result
        exc = Exception("NO_SUCHFILE: file doesn't exist")
        mock_reranker_retry = MagicMock()
        mock_reranker_retry.rerank.return_value = iter([])
        mock_tce.side_effect = [exc, mock_reranker_retry]

        _warmup()

        mock_clear.assert_called_once_with("org/rerank")

    @patch("wet_mcp.setup.run_auto_setup")
    @patch("qwen3_embed.TextCrossEncoder")
    @patch("qwen3_embed.TextEmbedding")
    @patch("wet_mcp.config.settings")
    def test_local_reranker_non_cache_error_reraises(
        self, mock_settings, mock_te, mock_tce, mock_setup
    ):
        """L146: non-cache reranker error is re-raised."""
        from wet_mcp.__main__ import _warmup

        mock_settings.setup_litellm.return_value = "local"
        mock_settings.resolve_local_embedding_model.return_value = "org/embed"
        mock_settings.resolve_local_rerank_model.return_value = "org/rerank"
        mock_settings.rerank_enabled = True

        mock_embed = MagicMock()
        mock_embed.embed.return_value = iter([np.array([0.1])])
        mock_te.return_value = mock_embed

        mock_tce.side_effect = ImportError("qwen3_embed broken")

        with pytest.raises(ImportError, match="broken"):
            _warmup()


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


class TestRerankerDictResult:
    """Cover reranker.py L95: LiteLLM returns dict items (proxy mode)."""

    def test_rerank_with_dict_results(self):
        from wet_mcp.reranker import LiteLLMReranker

        reranker = LiteLLMReranker("cohere/rerank-v3")

        mock_response = MagicMock()
        # Proxy returns dicts, not objects
        mock_response.results = [
            {"index": 0, "relevance_score": 0.8},
            {"index": 1, "relevance_score": 0.95},
        ]

        with patch("litellm.rerank", return_value=mock_response):
            results = reranker.rerank("query", ["doc1", "doc2"], top_n=2)

        assert results == [(1, 0.95), (0, 0.8)]
