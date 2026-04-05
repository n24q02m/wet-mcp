"""Tests for setup_tool module -- warmup and setup_sync as MCP-callable functions."""

from unittest.mock import AsyncMock, MagicMock, patch


class TestRunWarmup:
    """Tests for run_warmup() returning structured dict."""

    async def test_warmup_unhandled_exception(self):
        """Unhandled exception in warmup returns status: "error"."""
        with (
            patch("wet_mcp.setup.run_auto_setup"),
            patch("wet_mcp.setup_tool.settings") as mock_settings,
            patch(
                "wet_mcp.setup_tool._download_local_embedding",
                side_effect=Exception("unhandled error"),
            ),
        ):
            mock_settings.setup_providers.return_value = "local"
            from wet_mcp.setup_tool import run_warmup

            result = await run_warmup()

        assert result["status"] == "error"
        assert result["error"] == "unhandled error"

    async def test_warmup_returns_dict_with_status(self):
        """run_warmup() must return a dict with 'status' key."""
        with (
            patch("wet_mcp.setup.run_auto_setup"),
            patch("wet_mcp.setup_tool.settings") as mock_settings,
            patch("qwen3_embed.TextEmbedding") as mock_embed,
        ):
            mock_settings.setup_providers.return_value = "local"
            mock_settings.rerank_enabled = False
            mock_settings.resolve_local_embedding_model.return_value = "Qwen/test-model"
            mock_settings.resolve_local_rerank_model.return_value = "Qwen/test-reranker"
            mock_embed.return_value.embed.return_value = iter([[0.1] * 768])

            from wet_mcp.setup_tool import run_warmup

            result = await run_warmup()

        assert isinstance(result, dict)
        assert "status" in result
        assert result["status"] == "ok"

    async def test_warmup_cloud_models_success(self):
        """When cloud models are available, skip local downloads."""
        with (
            patch("wet_mcp.setup.run_auto_setup"),
            patch("wet_mcp.setup_tool.settings") as mock_settings,
            patch("wet_mcp.embedder.init_backend") as mock_init_backend,
            patch("wet_mcp.reranker.init_reranker") as mock_init_reranker,
        ):
            mock_settings.setup_providers.return_value = "sdk"
            mock_settings.resolve_embedding_model.return_value = (
                "text-embedding-3-large"
            )
            mock_settings.rerank_enabled = True
            mock_settings.resolve_rerank_model.return_value = "rerank-v3"

            mock_backend = MagicMock()
            mock_backend.check_available.return_value = 768
            mock_init_backend.return_value = mock_backend

            mock_reranker = MagicMock()
            mock_reranker.check_available.return_value = True
            mock_init_reranker.return_value = mock_reranker

            from wet_mcp.setup_tool import run_warmup

            result = await run_warmup()

        assert result["status"] == "ok"
        assert result["mode"] == "cloud"
        assert "embedding" in result
        assert "reranker" in result

    async def test_warmup_cloud_fallback_to_local(self):
        """When cloud fails, fall back to local model download."""
        with (
            patch("wet_mcp.setup.run_auto_setup"),
            patch("wet_mcp.setup_tool.settings") as mock_settings,
            patch("wet_mcp.embedder.init_backend") as mock_init_backend,
            patch("qwen3_embed.TextEmbedding") as mock_embed,
        ):
            mock_settings.setup_providers.return_value = "sdk"
            mock_settings.resolve_embedding_model.return_value = None
            mock_settings.rerank_enabled = False
            mock_settings.resolve_local_embedding_model.return_value = "Qwen/test-model"
            mock_settings.resolve_local_rerank_model.return_value = "Qwen/test-reranker"

            mock_init_backend.side_effect = Exception("no API key")

            mock_embed.return_value.embed.return_value = iter([[0.1] * 768])

            from wet_mcp.setup_tool import run_warmup

            result = await run_warmup()

        assert result["status"] == "ok"
        assert result["mode"] == "local"

    async def test_warmup_auto_setup_failure(self):
        """Auto-setup failure is reported but non-fatal."""
        with (
            patch(
                "wet_mcp.setup.run_auto_setup",
                side_effect=Exception("setup failed"),
            ),
            patch("wet_mcp.setup_tool.settings") as mock_settings,
            patch("qwen3_embed.TextEmbedding") as mock_embed,
        ):
            mock_settings.setup_providers.return_value = "local"
            mock_settings.rerank_enabled = False
            mock_settings.resolve_local_embedding_model.return_value = "Qwen/test-model"

            mock_embed.return_value.embed.return_value = iter([[0.1] * 768])

            from wet_mcp.setup_tool import run_warmup

            result = await run_warmup()

        assert result["status"] == "ok"
        assert "setup failed" in result["steps"][0]["error"]

    async def test_warmup_local_embedding_with_reranker(self):
        """Both local embedding and reranker are downloaded when rerank enabled."""
        with (
            patch("wet_mcp.setup.run_auto_setup"),
            patch("wet_mcp.setup_tool.settings") as mock_settings,
            patch("qwen3_embed.TextEmbedding") as mock_embed,
            patch("qwen3_embed.TextCrossEncoder") as mock_reranker,
        ):
            mock_settings.setup_providers.return_value = "local"
            mock_settings.rerank_enabled = True
            mock_settings.resolve_local_embedding_model.return_value = "Qwen/test-model"
            mock_settings.resolve_local_rerank_model.return_value = "Qwen/test-reranker"

            mock_embed.return_value.embed.return_value = iter([[0.1] * 768])
            mock_reranker.return_value.rerank.return_value = iter([0.9])

            from wet_mcp.setup_tool import run_warmup

            result = await run_warmup()

        assert result["status"] == "ok"
        assert result["mode"] == "local"
        assert any(s["step"] == "local_reranker" for s in result["steps"])

    async def test_warmup_corrupted_cache_retry(self):
        """Corrupted cache triggers clear + retry."""
        with (
            patch("wet_mcp.setup.run_auto_setup"),
            patch("wet_mcp.setup_tool.settings") as mock_settings,
            patch("wet_mcp.setup_tool.clear_model_cache") as mock_clear,
            patch("qwen3_embed.TextEmbedding") as mock_embed,
        ):
            mock_settings.setup_providers.return_value = "local"
            mock_settings.rerank_enabled = False
            mock_settings.resolve_local_embedding_model.return_value = "Qwen/test-model"

            call_count = 0

            def side_effect(*args, **kwargs):
                nonlocal call_count
                call_count += 1
                if call_count == 1:
                    raise RuntimeError("NO_SUCHFILE")
                mock_instance = MagicMock()
                mock_instance.embed.return_value = iter([[0.1] * 768])
                return mock_instance

            mock_embed.side_effect = side_effect

            from wet_mcp.setup_tool import run_warmup

            result = await run_warmup()

        assert result["status"] == "ok"
        mock_clear.assert_called_once()


class TestRunSetupSync:
    """Tests for run_setup_sync() returning structured dict."""

    async def test_setup_sync_returns_dict_with_status(self):
        """run_setup_sync() must return a dict with 'status' key."""
        with patch("wet_mcp.sync.setup_google_auth", return_value=True):
            from wet_mcp.setup_tool import run_setup_sync

            result = await run_setup_sync("drive")

        assert isinstance(result, dict)
        assert "status" in result
        assert result["status"] == "ok"

    async def test_setup_sync_auth_fails(self):
        """Returns error when auth fails."""
        with patch("wet_mcp.sync.setup_google_auth", return_value=False):
            from wet_mcp.setup_tool import run_setup_sync

            result = await run_setup_sync()

        assert result["status"] == "error"
        assert "failed" in result["error"].lower()

    async def test_setup_sync_exception(self):
        """Sync setup exception returns error dict."""
        with patch(
            "wet_mcp.sync.setup_google_auth",
            side_effect=Exception("auth error"),
        ):
            from wet_mcp.setup_tool import run_setup_sync

            result = await run_setup_sync()

        assert result["status"] == "error"
        assert "auth error" in result["error"]


class TestSetupMcpTool:
    """Tests for warmup/setup_sync actions in setup tool."""

    async def test_setup_tool_warmup_action(self):
        """setup tool with action='warmup' calls run_warmup."""
        with patch(
            "wet_mcp.setup_tool.run_warmup",
            new_callable=AsyncMock,
            return_value={"status": "ok", "steps": [], "mode": "local"},
        ):
            from wet_mcp.server import setup

            result = await setup(action="warmup")
            assert '"status": "ok"' in result

    async def test_setup_tool_setup_sync_action(self):
        """setup tool with action='setup_sync' calls run_setup_sync."""
        with patch(
            "wet_mcp.setup_tool.run_setup_sync",
            new_callable=AsyncMock,
            return_value={
                "status": "ok",
                "remote_type": "drive",
                "message": "Sync setup complete",
            },
        ):
            from wet_mcp.server import setup

            result = await setup(action="setup_sync", remote_type="drive")
            assert '"status": "ok"' in result

    async def test_setup_tool_invalid_action(self):
        """setup tool with invalid action returns error string."""
        from wet_mcp.server import setup

        result = await setup(action="invalid")
        assert '"error"' in result
        assert "Unknown action" in result

    async def test_setup_tool_setup_sync_default_remote(self):
        """setup_sync action without remote_type uses 'drive'."""
        with patch(
            "wet_mcp.setup_tool.run_setup_sync",
            new_callable=AsyncMock,
            return_value={
                "status": "ok",
                "remote_type": "drive",
                "message": "Sync setup complete",
            },
        ) as mock_sync:
            from wet_mcp.server import setup

            await setup(action="setup_sync")
            mock_sync.assert_called_once_with("drive")


class TestClearModelCache:
    """clear_model_cache removes corrupted HF Hub cache directories."""

    def test_removes_existing_cache(self, tmp_path):
        from wet_mcp.setup_tool import clear_model_cache

        model_dir = tmp_path / "models--org--model"
        model_dir.mkdir(parents=True)
        (model_dir / "refs").mkdir()
        (model_dir / "blobs").mkdir()
        (model_dir / "blobs" / "abc.incomplete").touch()

        with patch.dict("os.environ", {"QWEN3_EMBED_CACHE_PATH": str(tmp_path)}):
            result = clear_model_cache("org/model")

        assert not model_dir.exists()
        assert result is not None

    def test_noop_when_cache_missing(self, tmp_path):
        from wet_mcp.setup_tool import clear_model_cache

        with patch.dict("os.environ", {"QWEN3_EMBED_CACHE_PATH": str(tmp_path)}):
            result = clear_model_cache("nonexistent/model")

        assert result is None


class TestDownloadLocalEmbedding:
    """_download_local_embedding validates and downloads local models."""

    @patch("qwen3_embed.TextEmbedding")
    def test_embedding_success(self, mock_te):
        from wet_mcp.setup_tool import _download_local_embedding

        mock_settings = MagicMock()
        mock_settings.resolve_local_embedding_model.return_value = "org/embed"

        mock_model = MagicMock()
        import numpy as np

        mock_model.embed.return_value = iter([np.array([0.1, 0.2])])
        mock_te.return_value = mock_model

        result = _download_local_embedding(mock_settings)

        assert result["step"] == "local_embedding"
        assert result["status"] == "ok"
        assert result["dims"] == 2

    @patch("wet_mcp.setup_tool.clear_model_cache")
    @patch("qwen3_embed.TextEmbedding")
    def test_corrupted_cache_clears_and_retries(self, mock_te, mock_clear):
        from wet_mcp.setup_tool import _download_local_embedding

        mock_settings = MagicMock()
        mock_settings.resolve_local_embedding_model.return_value = "org/embed"

        mock_model_ok = MagicMock()
        import numpy as np

        mock_model_ok.embed.return_value = iter([np.array([0.1, 0.2])])

        exc = Exception("[ONNXRuntimeError] : 3 : NO_SUCHFILE : file doesn't exist")
        mock_te.side_effect = [exc, mock_model_ok]

        result = _download_local_embedding(mock_settings)

        mock_clear.assert_called_once_with("org/embed")
        assert result["status"] == "ok"
        assert result.get("retried") is True

    @patch("qwen3_embed.TextEmbedding")
    def test_non_cache_error_reraises(self, mock_te):
        from wet_mcp.setup_tool import _download_local_embedding

        mock_settings = MagicMock()
        mock_settings.resolve_local_embedding_model.return_value = "org/model"

        mock_te.side_effect = ImportError("qwen3_embed not installed")

        import pytest

        with pytest.raises(ImportError, match="not installed"):
            _download_local_embedding(mock_settings)

    @patch("qwen3_embed.TextEmbedding")
    def test_embedding_empty_result(self, mock_te):
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
    def test_embedding_empty_after_retry(self, mock_te, mock_clear):
        from wet_mcp.setup_tool import _download_local_embedding

        mock_settings = MagicMock()
        mock_settings.resolve_local_embedding_model.return_value = "org/embed"

        exc = Exception("NO_SUCHFILE")
        mock_model_empty = MagicMock()
        mock_model_empty.embed.return_value = iter([])
        mock_te.side_effect = [exc, mock_model_empty]

        result = _download_local_embedding(mock_settings)
        assert result["status"] == "warning"
        assert "after cache clear" in result["message"]


class TestDownloadLocalReranker:
    """_download_local_reranker validates and downloads local reranker."""

    def test_rerank_disabled_skips(self):
        from wet_mcp.setup_tool import _download_local_reranker

        mock_settings = MagicMock()
        mock_settings.rerank_enabled = False

        result = _download_local_reranker(mock_settings)
        assert result["status"] == "skipped"

    @patch("qwen3_embed.TextCrossEncoder")
    def test_reranker_success(self, mock_tce):
        from wet_mcp.setup_tool import _download_local_reranker

        mock_settings = MagicMock()
        mock_settings.rerank_enabled = True
        mock_settings.resolve_local_rerank_model.return_value = "org/rerank"

        mock_reranker = MagicMock()
        mock_reranker.rerank.return_value = iter([0.9])
        mock_tce.return_value = mock_reranker

        result = _download_local_reranker(mock_settings)
        assert result["status"] == "ok"

    @patch("wet_mcp.setup_tool.clear_model_cache")
    @patch("qwen3_embed.TextCrossEncoder")
    def test_corrupted_reranker_cache_retries(self, mock_tce, mock_clear):
        from wet_mcp.setup_tool import _download_local_reranker

        mock_settings = MagicMock()
        mock_settings.rerank_enabled = True
        mock_settings.resolve_local_rerank_model.return_value = "org/rerank"

        mock_reranker_ok = MagicMock()
        mock_reranker_ok.rerank.return_value = iter([0.9])
        exc = Exception("NO_SUCHFILE")
        mock_tce.side_effect = [exc, mock_reranker_ok]

        result = _download_local_reranker(mock_settings)
        mock_clear.assert_called_once_with("org/rerank")
        assert result["status"] == "ok"
        assert result.get("retried") is True

    @patch("qwen3_embed.TextCrossEncoder")
    def test_reranker_empty_result(self, mock_tce):
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
    def test_reranker_empty_after_retry(self, mock_tce, mock_clear):
        from wet_mcp.setup_tool import _download_local_reranker

        mock_settings = MagicMock()
        mock_settings.rerank_enabled = True
        mock_settings.resolve_local_rerank_model.return_value = "org/rerank"

        exc = Exception("NO_SUCHFILE")
        mock_reranker_empty = MagicMock()
        mock_reranker_empty.rerank.return_value = iter([])
        mock_tce.side_effect = [exc, mock_reranker_empty]

        result = _download_local_reranker(mock_settings)
        assert result["status"] == "warning"

    @patch("qwen3_embed.TextCrossEncoder")
    def test_reranker_non_cache_error_reraises(self, mock_tce):
        from wet_mcp.setup_tool import _download_local_reranker

        mock_settings = MagicMock()
        mock_settings.rerank_enabled = True
        mock_settings.resolve_local_rerank_model.return_value = "org/rerank"

        mock_tce.side_effect = RuntimeError("GPU not available")

        import pytest

        with pytest.raises(RuntimeError, match="GPU not available"):
            _download_local_reranker(mock_settings)


class TestValidateCloudModels:
    """_validate_cloud_models checks cloud embedding and reranking."""

    @patch("wet_mcp.setup_tool._EMBEDDING_CANDIDATES", ["gemini/embed-1"])
    @patch("wet_mcp.reranker.init_reranker")
    @patch("wet_mcp.embedder.init_backend")
    def test_cloud_embedding_and_reranker_success(self, mock_init, mock_rr_init):
        from wet_mcp.setup_tool import _validate_cloud_models

        mock_settings = MagicMock()
        mock_settings.resolve_embedding_model.return_value = None
        mock_settings.resolve_rerank_model.return_value = "cohere/rerank"

        mock_backend = MagicMock()
        mock_backend.check_available.return_value = 768
        mock_init.return_value = mock_backend

        mock_reranker = MagicMock()
        mock_reranker.check_available.return_value = True
        mock_rr_init.return_value = mock_reranker

        result = _validate_cloud_models(mock_settings)

        assert result["cloud_ready"] is True
        assert result["embedding"]["model"] == "gemini/embed-1"
        assert result["reranker"]["model"] == "cohere/rerank"

    @patch("wet_mcp.setup_tool._EMBEDDING_CANDIDATES", ["model-a"])
    @patch("wet_mcp.embedder.init_backend")
    def test_cloud_embedding_fails(self, mock_init):
        from wet_mcp.setup_tool import _validate_cloud_models

        mock_settings = MagicMock()
        mock_settings.resolve_embedding_model.return_value = None

        mock_backend = MagicMock()
        mock_backend.check_available.return_value = 0
        mock_init.return_value = mock_backend

        result = _validate_cloud_models(mock_settings)
        assert result["cloud_ready"] is False

    @patch("wet_mcp.setup_tool._EMBEDDING_CANDIDATES", ["gemini/embed"])
    @patch("wet_mcp.reranker.init_reranker")
    @patch("wet_mcp.embedder.init_backend")
    def test_cloud_reranker_fails(self, mock_init, mock_rr_init):
        from wet_mcp.setup_tool import _validate_cloud_models

        mock_settings = MagicMock()
        mock_settings.resolve_embedding_model.return_value = None
        mock_settings.resolve_rerank_model.return_value = "cohere/rerank"

        mock_backend = MagicMock()
        mock_backend.check_available.return_value = 768
        mock_init.return_value = mock_backend

        mock_reranker = MagicMock()
        mock_reranker.check_available.return_value = False
        mock_rr_init.return_value = mock_reranker

        result = _validate_cloud_models(mock_settings)
        assert result["cloud_ready"] is True
        assert result["reranker"] is None

    @patch("wet_mcp.setup_tool._EMBEDDING_CANDIDATES", ["gemini/embed"])
    @patch("wet_mcp.reranker.init_reranker")
    @patch("wet_mcp.embedder.init_backend")
    def test_cloud_reranker_init_exception(self, mock_init, mock_rr_init):
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

    @patch("wet_mcp.setup_tool._EMBEDDING_CANDIDATES", ["gemini/embed"])
    @patch("wet_mcp.embedder.init_backend")
    def test_explicit_model_tried_first(self, mock_init):
        from wet_mcp.setup_tool import _validate_cloud_models

        mock_settings = MagicMock()
        mock_settings.resolve_embedding_model.return_value = "explicit/model"
        mock_settings.resolve_rerank_model.return_value = None

        mock_backend = MagicMock()
        mock_backend.check_available.return_value = 512
        mock_init.return_value = mock_backend

        result = _validate_cloud_models(mock_settings)

        mock_init.assert_called_once_with("cloud", "explicit/model")
        assert result["cloud_ready"] is True

    @patch("wet_mcp.setup_tool._EMBEDDING_CANDIDATES", ["gemini/embed"])
    @patch("wet_mcp.embedder.init_backend")
    def test_no_rerank_model_skips_check(self, mock_init):
        from wet_mcp.setup_tool import _validate_cloud_models

        mock_settings = MagicMock()
        mock_settings.resolve_embedding_model.return_value = None
        mock_settings.resolve_rerank_model.return_value = None

        mock_backend = MagicMock()
        mock_backend.check_available.return_value = 768
        mock_init.return_value = mock_backend

        result = _validate_cloud_models(mock_settings)
        assert result["cloud_ready"] is True
        assert result["reranker"] is None

    @patch("wet_mcp.setup_tool._EMBEDDING_CANDIDATES", ["model-a"])
    @patch("wet_mcp.embedder.init_backend")
    def test_cloud_exception_returns_not_ready(self, mock_init):
        from wet_mcp.setup_tool import _validate_cloud_models

        mock_settings = MagicMock()
        mock_settings.resolve_embedding_model.return_value = None

        mock_init.side_effect = Exception("init failed")

        result = _validate_cloud_models(mock_settings)
        assert result["cloud_ready"] is False
