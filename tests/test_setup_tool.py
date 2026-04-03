"""Tests for setup_tool module -- warmup and setup_sync as MCP-callable functions."""

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestClearModelCache:
    """Tests for clear_model_cache()."""

    def test_clear_model_cache_exists(self, tmp_path):
        """Removes model cache directory if it exists."""
        from wet_mcp.setup_tool import clear_model_cache

        cache_dir = tmp_path / "qwen3_embed_cache"
        cache_dir.mkdir()
        model_dir = cache_dir / "models--test--model"
        model_dir.mkdir()
        (model_dir / "test.bin").write_text("data")

        with patch.dict(os.environ, {"QWEN3_EMBED_CACHE_PATH": str(cache_dir)}):
            result = clear_model_cache("test/model")
            assert result == str(model_dir)
            assert not model_dir.exists()

    def test_clear_model_cache_not_exists(self, tmp_path):
        """Returns None if model cache directory does not exist."""
        from wet_mcp.setup_tool import clear_model_cache

        cache_dir = tmp_path / "qwen3_embed_cache"
        cache_dir.mkdir()

        with patch.dict(os.environ, {"QWEN3_EMBED_CACHE_PATH": str(cache_dir)}):
            result = clear_model_cache("nonexistent/model")
            assert result is None


class TestValidateCloudModels:
    """Tests for _validate_cloud_models()."""

    def test_validate_cloud_models_success(self):
        """Returns cloud_ready=True when models are available."""
        from wet_mcp.setup_tool import _validate_cloud_models

        mock_settings = MagicMock()
        mock_settings.resolve_embedding_model.return_value = "test-embed"
        mock_settings.resolve_rerank_model.return_value = "test-rerank"

        mock_backend = MagicMock()
        mock_backend.check_available.return_value = 768
        mock_reranker = MagicMock()
        mock_reranker.check_available.return_value = True

        with (
            patch("wet_mcp.embedder.init_backend", return_value=mock_backend),
            patch("wet_mcp.reranker.init_reranker", return_value=mock_reranker),
        ):
            result = _validate_cloud_models(mock_settings)

        assert result["cloud_ready"] is True
        assert result["embedding"]["model"] == "test-embed"
        assert result["embedding"]["dims"] == 768
        assert result["reranker"]["model"] == "test-rerank"

    def test_validate_cloud_models_no_embedding(self):
        """Returns cloud_ready=False when no embedding model is available."""
        from wet_mcp.setup_tool import _validate_cloud_models

        mock_settings = MagicMock()
        mock_settings.resolve_embedding_model.return_value = "test-embed"

        with patch("wet_mcp.embedder.init_backend", side_effect=Exception("failed")):
            result = _validate_cloud_models(mock_settings)

        assert result["cloud_ready"] is False

    def test_validate_cloud_models_no_reranker(self):
        """Still returns cloud_ready=True if only reranker fails."""
        from wet_mcp.setup_tool import _validate_cloud_models

        mock_settings = MagicMock()
        mock_settings.resolve_embedding_model.return_value = "test-embed"
        mock_settings.resolve_rerank_model.return_value = "test-rerank"

        mock_backend = MagicMock()
        mock_backend.check_available.return_value = 768

        with (
            patch("wet_mcp.embedder.init_backend", return_value=mock_backend),
            patch("wet_mcp.reranker.init_reranker", side_effect=Exception("failed")),
        ):
            result = _validate_cloud_models(mock_settings)

        assert result["cloud_ready"] is True
        assert result["reranker"] is None


class TestDownloadLocalModels:
    """Tests for _download_local_embedding and _download_local_reranker."""

    def test_download_local_embedding_success(self):
        """Successfully downloads local embedding."""
        from wet_mcp.setup_tool import _download_local_embedding

        mock_settings = MagicMock()
        mock_settings.resolve_local_embedding_model.return_value = "local-model"

        mock_embed = MagicMock()
        mock_embed.embed.return_value = iter([[0.1, 0.2]])

        with patch("qwen3_embed.TextEmbedding", return_value=mock_embed):
            result = _download_local_embedding(mock_settings)

        assert result["status"] == "ok"
        assert result["model"] == "local-model"
        assert result["dims"] == 2

    def test_download_local_embedding_empty_result(self):
        """Returns warning when embedding returns empty."""
        from wet_mcp.setup_tool import _download_local_embedding

        mock_settings = MagicMock()
        mock_settings.resolve_local_embedding_model.return_value = "local-model"

        mock_embed = MagicMock()
        mock_embed.embed.return_value = iter([])

        with patch("qwen3_embed.TextEmbedding", return_value=mock_embed):
            result = _download_local_embedding(mock_settings)

        assert result["status"] == "warning"
        assert "empty result" in result["message"]

    def test_download_local_embedding_retry_success(self):
        """Retries download after clearing cache on NO_SUCHFILE."""
        from wet_mcp.setup_tool import _download_local_embedding

        mock_settings = MagicMock()
        mock_settings.resolve_local_embedding_model.return_value = "local-model"

        call_count = 0

        def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("NO_SUCHFILE")
            mock_embed = MagicMock()
            mock_embed.embed.return_value = iter([[0.1]])
            return mock_embed

        with (
            patch("qwen3_embed.TextEmbedding", side_effect=side_effect),
            patch("wet_mcp.setup_tool.clear_model_cache") as mock_clear,
        ):
            result = _download_local_embedding(mock_settings)

        assert result["status"] == "ok"
        assert result.get("retried") is True
        mock_clear.assert_called_once_with("local-model")

    def test_download_local_embedding_retry_fails(self):
        """Returns warning if retry also fails."""
        from wet_mcp.setup_tool import _download_local_embedding

        mock_settings = MagicMock()
        mock_settings.resolve_local_embedding_model.return_value = "local-model"

        call_count = 0

        def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("NO_SUCHFILE")
            mock_embed = MagicMock()
            mock_embed.embed.return_value = iter([])
            return mock_embed

        with (
            patch("qwen3_embed.TextEmbedding", side_effect=side_effect),
            patch("wet_mcp.setup_tool.clear_model_cache"),
        ):
            result = _download_local_embedding(mock_settings)

        assert result["status"] == "warning"
        assert "failed after cache clear" in result["message"]

    def test_download_local_reranker_success(self):
        """Successfully downloads local reranker."""
        from wet_mcp.setup_tool import _download_local_reranker

        mock_settings = MagicMock()
        mock_settings.rerank_enabled = True
        mock_settings.resolve_local_rerank_model.return_value = "local-rerank"

        mock_reranker = MagicMock()
        mock_reranker.rerank.return_value = iter([0.9])

        with patch("qwen3_embed.TextCrossEncoder", return_value=mock_reranker):
            result = _download_local_reranker(mock_settings)

        assert result["status"] == "ok"
        assert result["model"] == "local-rerank"

    def test_download_local_reranker_skipped(self):
        """Skips reranker download if disabled."""
        from wet_mcp.setup_tool import _download_local_reranker

        mock_settings = MagicMock()
        mock_settings.rerank_enabled = False

        result = _download_local_reranker(mock_settings)
        assert result["status"] == "skipped"

    def test_download_local_reranker_empty_result(self):
        """Returns warning when reranker returns empty."""
        from wet_mcp.setup_tool import _download_local_reranker

        mock_settings = MagicMock()
        mock_settings.rerank_enabled = True
        mock_settings.resolve_local_rerank_model.return_value = "local-rerank"

        mock_reranker = MagicMock()
        mock_reranker.rerank.return_value = iter([])

        with patch("qwen3_embed.TextCrossEncoder", return_value=mock_reranker):
            result = _download_local_reranker(mock_settings)

        assert result["status"] == "warning"
        assert "empty result" in result["message"]

    def test_download_local_reranker_retry_success(self):
        """Retries reranker download after clearing cache on NO_SUCHFILE."""
        from wet_mcp.setup_tool import _download_local_reranker

        mock_settings = MagicMock()
        mock_settings.rerank_enabled = True
        mock_settings.resolve_local_rerank_model.return_value = "local-rerank"

        call_count = 0

        def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("NO_SUCHFILE")
            mock_reranker = MagicMock()
            mock_reranker.rerank.return_value = iter([0.5])
            return mock_reranker

        with (
            patch("qwen3_embed.TextCrossEncoder", side_effect=side_effect),
            patch("wet_mcp.setup_tool.clear_model_cache") as mock_clear,
        ):
            result = _download_local_reranker(mock_settings)

        assert result["status"] == "ok"
        assert result.get("retried") is True
        mock_clear.assert_called_once_with("local-rerank")

    def test_download_local_reranker_retry_fails(self):
        """Returns warning if reranker retry also fails."""
        from wet_mcp.setup_tool import _download_local_reranker

        mock_settings = MagicMock()
        mock_settings.rerank_enabled = True
        mock_settings.resolve_local_rerank_model.return_value = "local-rerank"

        call_count = 0

        def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("NO_SUCHFILE")
            mock_reranker = MagicMock()
            mock_reranker.rerank.return_value = iter([])
            return mock_reranker

        with (
            patch("qwen3_embed.TextCrossEncoder", side_effect=side_effect),
            patch("wet_mcp.setup_tool.clear_model_cache"),
        ):
            result = _download_local_reranker(mock_settings)

        assert result["status"] == "warning"
        assert "failed after cache clear" in result["message"]


class TestRunWarmup:
    """Tests for run_warmup() returning structured dict."""

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
        assert result["provider"] == "google_drive"

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

    async def test_setup_sync_custom_remote(self):
        """Works with custom remote_type (passed to function)."""
        with patch("wet_mcp.sync.setup_google_auth", return_value=True):
            from wet_mcp.setup_tool import run_setup_sync

            result = await run_setup_sync("custom_remote")
            assert result["status"] == "ok"


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

    def test_download_local_embedding_unexpected_exception(self):
        """Unexpected exception in _download_local_embedding is re-raised."""
        from wet_mcp.setup_tool import _download_local_embedding

        mock_settings = MagicMock()
        mock_settings.resolve_local_embedding_model.return_value = "local-model"

        with patch("qwen3_embed.TextEmbedding", side_effect=ValueError("unexpected")):
            with pytest.raises(ValueError, match="unexpected"):
                _download_local_embedding(mock_settings)

    def test_download_local_reranker_unexpected_exception(self):
        """Unexpected exception in _download_local_reranker is re-raised."""
        from wet_mcp.setup_tool import _download_local_reranker

        mock_settings = MagicMock()
        mock_settings.rerank_enabled = True
        mock_settings.resolve_local_rerank_model.return_value = "local-rerank"

        with patch(
            "qwen3_embed.TextCrossEncoder", side_effect=ValueError("unexpected")
        ):
            with pytest.raises(ValueError, match="unexpected"):
                _download_local_reranker(mock_settings)

    def test_validate_cloud_models_dims_zero(self):
        """Skip candidate if check_available returns 0."""
        from wet_mcp.setup_tool import _validate_cloud_models

        mock_settings = MagicMock()
        mock_settings.resolve_embedding_model.return_value = "test-embed"

        mock_backend = MagicMock()
        mock_backend.check_available.return_value = 0

        with patch("wet_mcp.embedder.init_backend", return_value=mock_backend):
            result = _validate_cloud_models(mock_settings)

        assert result["cloud_ready"] is False

    def test_validate_cloud_models_reranker_not_available(self):
        """Reranker info is None if check_available returns False."""
        from wet_mcp.setup_tool import _validate_cloud_models

        mock_settings = MagicMock()
        mock_settings.resolve_embedding_model.return_value = "test-embed"
        mock_settings.resolve_rerank_model.return_value = "test-rerank"

        mock_backend = MagicMock()
        mock_backend.check_available.return_value = 768
        mock_reranker = MagicMock()
        mock_reranker.check_available.return_value = False

        with (
            patch("wet_mcp.embedder.init_backend", return_value=mock_backend),
            patch("wet_mcp.reranker.init_reranker", return_value=mock_reranker),
        ):
            result = _validate_cloud_models(mock_settings)

        assert result["cloud_ready"] is True
        assert result["reranker"] is None

    def test_validate_cloud_models_no_rerank_model(self):
        """Reranker info is None if no rerank model configured."""
        from wet_mcp.setup_tool import _validate_cloud_models

        mock_settings = MagicMock()
        mock_settings.resolve_embedding_model.return_value = "test-embed"
        mock_settings.resolve_rerank_model.return_value = None

        mock_backend = MagicMock()
        mock_backend.check_available.return_value = 768

        with patch("wet_mcp.embedder.init_backend", return_value=mock_backend):
            result = _validate_cloud_models(mock_settings)

        assert result["cloud_ready"] is True
        assert result["reranker"] is None
