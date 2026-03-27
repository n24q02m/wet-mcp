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
    """Tests for the setup MCP tool registration."""

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
