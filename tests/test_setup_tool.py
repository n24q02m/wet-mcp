"""Tests for setup_tool module -- warmup and setup_sync as MCP-callable functions."""

from unittest.mock import AsyncMock, MagicMock, patch


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

    async def test_setup_sync_success_details(self):
        """run_setup_sync() returns detailed success info and calls auth."""
        with patch(
            "wet_mcp.sync.setup_google_auth", new_callable=AsyncMock, return_value=True
        ) as mock_auth:
            from wet_mcp.setup_tool import run_setup_sync

            result = await run_setup_sync("drive")

        assert result == {
            "status": "ok",
            "provider": "google_drive",
            "message": "Google Drive sync setup complete. Token saved locally.",
        }
        mock_auth.assert_called_once()

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
    """Tests for warmup/setup_sync actions merged into config tool."""

    async def test_config_tool_warmup_action(self):
        """config tool with action='warmup' calls run_warmup."""
        with patch(
            "wet_mcp.setup_tool.run_warmup",
            new_callable=AsyncMock,
            return_value={"status": "ok", "steps": [], "mode": "local"},
        ):
            from wet_mcp.server import config

            result = await config(action="warmup")
            assert '"status": "ok"' in result

    async def test_config_tool_setup_sync_action(self):
        """config tool with action='setup_sync' calls run_setup_sync."""
        with patch(
            "wet_mcp.setup_tool.run_setup_sync",
            new_callable=AsyncMock,
            return_value={
                "status": "ok",
                "remote_type": "drive",
                "message": "Sync setup complete",
            },
        ):
            from wet_mcp.server import config

            result = await config(action="setup_sync", remote_type="drive")
            assert '"status": "ok"' in result

    async def test_config_tool_invalid_action(self):
        """config tool with invalid action returns error string."""
        from wet_mcp.server import config

        result = await config(action="invalid")
        assert '"error"' in result
        assert "Unknown action" in result

    async def test_config_tool_setup_sync_default_remote(self):
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
            from wet_mcp.server import config

            await config(action="setup_sync")
            mock_sync.assert_called_once_with("drive")


class TestSetupToolCoverage:
    """Extra tests to fill coverage gaps in setup_tool.py."""

    def test_clear_model_cache(self, tmp_path):
        """clear_model_cache() removes the correct directory."""
        import os

        from wet_mcp.setup_tool import clear_model_cache

        # Mock cache path via env var
        cache_root = tmp_path / "cache"
        cache_root.mkdir()

        with patch.dict(os.environ, {"QWEN3_EMBED_CACHE_PATH": str(cache_root)}):
            model_name = "test/model"
            safe_name = "test--model"
            model_dir = cache_root / f"models--{safe_name}"
            model_dir.mkdir()

            assert model_dir.exists()
            result = clear_model_cache(model_name)
            assert result == str(model_dir)
            assert not model_dir.exists()

            # Call again when it doesn't exist
            assert clear_model_cache(model_name) is None

    def test_validate_cloud_models_no_embedding(self):
        """_validate_cloud_models returns cloud_ready=False if no embedding models found."""
        from wet_mcp.setup_tool import _validate_cloud_models

        mock_settings = MagicMock()
        mock_settings.resolve_embedding_model.return_value = None

        with patch(
            "wet_mcp.embedder.init_backend", side_effect=Exception("no backend")
        ):
            result = _validate_cloud_models(mock_settings)

        assert result["cloud_ready"] is False

    def test_validate_cloud_models_reranker_fail(self):
        """_validate_cloud_models handles reranker initialization failure gracefully."""
        from wet_mcp.setup_tool import _validate_cloud_models

        mock_settings = MagicMock()
        mock_settings.resolve_embedding_model.return_value = "emb"
        mock_settings.resolve_rerank_model.return_value = "reranker"

        mock_backend = MagicMock()
        mock_backend.check_available.return_value = 768

        with (
            patch("wet_mcp.embedder.init_backend", return_value=mock_backend),
            patch(
                "wet_mcp.reranker.init_reranker", side_effect=Exception("rerank fail")
            ),
        ):
            result = _validate_cloud_models(mock_settings)

        assert result["cloud_ready"] is True
        assert result["reranker"] is None

    def test_download_local_embedding_empty_result(self):
        """_download_local_embedding handles empty embedding result."""
        from wet_mcp.setup_tool import _download_local_embedding

        mock_settings = MagicMock()
        mock_settings.resolve_local_embedding_model.return_value = "model"

        mock_embed = MagicMock()
        mock_embed.embed.return_value = []

        with patch("qwen3_embed.TextEmbedding", return_value=mock_embed):
            result = _download_local_embedding(mock_settings)

        assert result["status"] == "warning"
        assert "empty result" in result["message"]

    def test_download_local_embedding_retry_fail(self):
        """_download_local_embedding handles failure after cache clear."""
        from wet_mcp.setup_tool import _download_local_embedding

        mock_settings = MagicMock()
        mock_settings.resolve_local_embedding_model.return_value = "model"

        # First call raises NO_SUCHFILE, second call returns empty list
        def side_effect(*args, **kwargs):
            if side_effect.called:
                m = MagicMock()
                m.embed.return_value = []
                return m
            side_effect.called = True
            raise RuntimeError("NO_SUCHFILE")

        side_effect.called = False

        with (
            patch("qwen3_embed.TextEmbedding", side_effect=side_effect),
            patch("wet_mcp.setup_tool.clear_model_cache"),
        ):
            result = _download_local_embedding(mock_settings)

        assert result["status"] == "warning"
        assert "failed after cache clear" in result["message"]

    def test_download_local_reranker_empty_result(self):
        """_download_local_reranker handles empty scores."""
        from wet_mcp.setup_tool import _download_local_reranker

        mock_settings = MagicMock()
        mock_settings.rerank_enabled = True
        mock_settings.resolve_local_rerank_model.return_value = "model"

        mock_reranker = MagicMock()
        mock_reranker.rerank.return_value = []

        with patch("qwen3_embed.TextCrossEncoder", return_value=mock_reranker):
            result = _download_local_reranker(mock_settings)

        assert result["status"] == "warning"
        assert "empty result" in result["message"]

    def test_download_local_reranker_retry_success(self):
        """_download_local_reranker retries successfully after NO_SUCHFILE."""
        from wet_mcp.setup_tool import _download_local_reranker

        mock_settings = MagicMock()
        mock_settings.rerank_enabled = True
        mock_settings.resolve_local_rerank_model.return_value = "model"

        def side_effect(*args, **kwargs):
            if side_effect.called:
                m = MagicMock()
                m.rerank.return_value = [0.9]
                return m
            side_effect.called = True
            raise RuntimeError("NO_SUCHFILE")

        side_effect.called = False

        with (
            patch("qwen3_embed.TextCrossEncoder", side_effect=side_effect),
            patch("wet_mcp.setup_tool.clear_model_cache"),
        ):
            result = _download_local_reranker(mock_settings)

        assert result["status"] == "ok"
        assert result.get("retried") is True

    def test_download_local_reranker_retry_fail(self):
        """_download_local_reranker handles failure after cache clear."""
        from wet_mcp.setup_tool import _download_local_reranker

        mock_settings = MagicMock()
        mock_settings.rerank_enabled = True
        mock_settings.resolve_local_rerank_model.return_value = "model"

        def side_effect(*args, **kwargs):
            if side_effect.called:
                m = MagicMock()
                m.rerank.return_value = []
                return m
            side_effect.called = True
            raise RuntimeError("NO_SUCHFILE")

        side_effect.called = False

        with (
            patch("qwen3_embed.TextCrossEncoder", side_effect=side_effect),
            patch("wet_mcp.setup_tool.clear_model_cache"),
        ):
            result = _download_local_reranker(mock_settings)

        assert result["status"] == "warning"
        assert "failed after cache clear" in result["message"]
