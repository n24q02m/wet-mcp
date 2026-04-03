from unittest.mock import MagicMock, patch

import pytest

# Do not import wet_mcp at top level to avoid collection error
# from wet_mcp.setup_tool import ...


@pytest.fixture
def setup_tool_mod():
    import wet_mcp.setup_tool

    return wet_mcp.setup_tool


def test_clear_model_cache_exists(setup_tool_mod):
    """Test clear_model_cache when the cache directory exists."""
    with patch("wet_mcp.setup_tool.Path") as mock_path:
        mock_instance = mock_path.return_value
        mock_instance.__truediv__.return_value = mock_instance
        mock_instance.exists.return_value = True

        with patch("shutil.rmtree") as mock_rmtree:
            result = setup_tool_mod.clear_model_cache("test/model")

            assert result is not None
            mock_rmtree.assert_called_once()


def test_clear_model_cache_not_exists(setup_tool_mod):
    """Test clear_model_cache when the cache directory does not exist."""
    with patch("wet_mcp.setup_tool.Path") as mock_path:
        mock_instance = mock_path.return_value
        mock_instance.__truediv__.return_value = mock_instance
        mock_instance.exists.return_value = False

        result = setup_tool_mod.clear_model_cache("test/model")
        assert result is None


def test_validate_cloud_models_embedding_dims_zero(setup_tool_mod):
    """Test _validate_cloud_models when embedding check_available returns 0."""
    mock_settings = MagicMock()
    mock_settings.resolve_embedding_model.return_value = "some-model"

    with patch("wet_mcp.embedder.init_backend") as mock_init:
        mock_backend = MagicMock()
        mock_backend.check_available.return_value = 0
        mock_init.return_value = mock_backend

        result = setup_tool_mod._validate_cloud_models(mock_settings)
        assert result == {"cloud_ready": False}


def test_validate_cloud_models_reranker_not_available(setup_tool_mod):
    """Test _validate_cloud_models when reranker is not available."""
    mock_settings = MagicMock()
    mock_settings.resolve_embedding_model.return_value = "some-model"
    mock_settings.resolve_rerank_model.return_value = "rerank-model"

    with (
        patch("wet_mcp.embedder.init_backend") as mock_init_backend,
        patch("wet_mcp.reranker.init_reranker") as mock_init_reranker,
    ):
        mock_backend = MagicMock()
        mock_backend.check_available.return_value = 768
        mock_init_backend.return_value = mock_backend

        mock_reranker = MagicMock()
        mock_reranker.check_available.return_value = False
        mock_init_reranker.return_value = mock_reranker

        result = setup_tool_mod._validate_cloud_models(mock_settings)
        assert result["cloud_ready"] is True
        assert result["reranker"] is None


def test_validate_cloud_models_reranker_exception(setup_tool_mod):
    """Test _validate_cloud_models when init_reranker raises exception."""
    mock_settings = MagicMock()
    mock_settings.resolve_embedding_model.return_value = "some-model"
    mock_settings.resolve_rerank_model.return_value = "rerank-model"

    with (
        patch("wet_mcp.embedder.init_backend") as mock_init_backend,
        patch("wet_mcp.reranker.init_reranker") as mock_init_reranker,
    ):
        mock_backend = MagicMock()
        mock_backend.check_available.return_value = 768
        mock_init_backend.return_value = mock_backend

        mock_init_reranker.side_effect = Exception("init failed")

        result = setup_tool_mod._validate_cloud_models(mock_settings)
        assert result["cloud_ready"] is True
        assert result["reranker"] is None


def test_validate_cloud_models_multiple_candidates(setup_tool_mod):
    """Test _validate_cloud_models trying multiple candidates when first fails."""
    mock_settings = MagicMock()
    mock_settings.resolve_embedding_model.return_value = (
        None  # Use _EMBEDDING_CANDIDATES
    )

    with (
        patch("wet_mcp.embedder.init_backend") as mock_init,
        patch("wet_mcp.setup_tool._EMBEDDING_CANDIDATES", ["fail-model", "ok-model"]),
    ):
        mock_backend_fail = MagicMock()
        mock_backend_fail.check_available.side_effect = Exception("fail")

        mock_backend_ok = MagicMock()
        mock_backend_ok.check_available.return_value = 1536

        mock_init.side_effect = [mock_backend_fail, mock_backend_ok]

        result = setup_tool_mod._validate_cloud_models(mock_settings)
        assert result["cloud_ready"] is True
        assert result["embedding"]["model"] == "ok-model"
        assert result["embedding"]["dims"] == 1536


def test_download_local_embedding_empty_result(setup_tool_mod):
    """Test _download_local_embedding when embed returns empty list."""
    mock_settings = MagicMock()
    mock_settings.resolve_local_embedding_model.return_value = "local-model"

    with patch("qwen3_embed.TextEmbedding") as mock_embed_cls:
        mock_embed = mock_embed_cls.return_value
        mock_embed.embed.return_value = iter([])

        result = setup_tool_mod._download_local_embedding(mock_settings)
        assert result["status"] == "warning"
        assert "empty result" in result["message"]


def test_download_local_embedding_retry_fail(setup_tool_mod):
    """Test _download_local_embedding retry logic when it fails again."""
    mock_settings = MagicMock()
    mock_settings.resolve_local_embedding_model.return_value = "local-model"

    with (
        patch("qwen3_embed.TextEmbedding") as mock_embed_cls,
        patch("wet_mcp.setup_tool.clear_model_cache"),
    ):
        # First call fails with NO_SUCHFILE
        # Second call returns empty list
        mock_embed_cls.side_effect = [
            RuntimeError("NO_SUCHFILE"),
            MagicMock(embed=MagicMock(return_value=iter([]))),
        ]

        result = setup_tool_mod._download_local_embedding(mock_settings)
        assert result["status"] == "warning"
        assert "failed after cache clear" in result["message"]


def test_download_local_reranker_empty_result(setup_tool_mod):
    """Test _download_local_reranker when rerank returns empty list."""
    mock_settings = MagicMock()
    mock_settings.rerank_enabled = True
    mock_settings.resolve_local_rerank_model.return_value = "local-rerank"

    with patch("qwen3_embed.TextCrossEncoder") as mock_rerank_cls:
        mock_rerank = mock_rerank_cls.return_value
        mock_rerank.rerank.return_value = iter([])

        result = setup_tool_mod._download_local_reranker(mock_settings)
        assert result["status"] == "warning"
        assert "empty result" in result["message"]


def test_download_local_reranker_retry_success(setup_tool_mod):
    """Test _download_local_reranker retry logic when it succeeds."""
    mock_settings = MagicMock()
    mock_settings.rerank_enabled = True
    mock_settings.resolve_local_rerank_model.return_value = "local-rerank"

    with (
        patch("qwen3_embed.TextCrossEncoder") as mock_rerank_cls,
        patch("wet_mcp.setup_tool.clear_model_cache"),
    ):
        mock_rerank_ok = MagicMock()
        mock_rerank_ok.rerank.return_value = iter([0.8])

        mock_rerank_cls.side_effect = [RuntimeError("doesn't exist"), mock_rerank_ok]

        result = setup_tool_mod._download_local_reranker(mock_settings)
        assert result["status"] == "ok"
        assert result.get("retried") is True


def test_download_local_reranker_retry_fail(setup_tool_mod):
    """Test _download_local_reranker retry logic when it fails again."""
    mock_settings = MagicMock()
    mock_settings.rerank_enabled = True
    mock_settings.resolve_local_rerank_model.return_value = "local-rerank"

    with (
        patch("qwen3_embed.TextCrossEncoder") as mock_rerank_cls,
        patch("wet_mcp.setup_tool.clear_model_cache"),
    ):
        mock_rerank_fail = MagicMock()
        mock_rerank_fail.rerank.return_value = iter([])

        mock_rerank_cls.side_effect = [RuntimeError("NO_SUCHFILE"), mock_rerank_fail]

        result = setup_tool_mod._download_local_reranker(mock_settings)
        assert result["status"] == "warning"
        assert "failed after cache clear" in result["message"]


def test_download_local_embedding_other_exception(setup_tool_mod):
    """Test _download_local_embedding when a non-NO_SUCHFILE exception is raised."""
    mock_settings = MagicMock()
    mock_settings.resolve_local_embedding_model.return_value = "local-model"

    with patch("qwen3_embed.TextEmbedding") as mock_embed_cls:
        mock_embed_cls.side_effect = Exception("Other error")

        with pytest.raises(Exception, match="Other error"):
            setup_tool_mod._download_local_embedding(mock_settings)


def test_download_local_reranker_other_exception(setup_tool_mod):
    """Test _download_local_reranker when a non-NO_SUCHFILE exception is raised."""
    mock_settings = MagicMock()
    mock_settings.rerank_enabled = True
    mock_settings.resolve_local_rerank_model.return_value = "local-rerank"

    with patch("qwen3_embed.TextCrossEncoder") as mock_rerank_cls:
        mock_rerank_cls.side_effect = Exception("Other rerank error")

        with pytest.raises(Exception, match="Other rerank error"):
            setup_tool_mod._download_local_reranker(mock_settings)


def test_validate_cloud_models_reranker_none(setup_tool_mod):
    """Test _validate_cloud_models when rerank_model is None."""
    mock_settings = MagicMock()
    mock_settings.resolve_embedding_model.return_value = "some-model"
    mock_settings.resolve_rerank_model.return_value = None

    with patch("wet_mcp.embedder.init_backend") as mock_init_backend:
        mock_backend = MagicMock()
        mock_backend.check_available.return_value = 768
        mock_init_backend.return_value = mock_backend

        result = setup_tool_mod._validate_cloud_models(mock_settings)
        assert result["cloud_ready"] is True
        assert result["reranker"] is None


@pytest.mark.asyncio
async def test_run_warmup_full_local_flow(setup_tool_mod):
    """Test the full orchestration of run_warmup in local mode."""
    with (
        patch("wet_mcp.setup.run_auto_setup"),
        patch("wet_mcp.setup_tool.settings") as mock_settings,
        patch("wet_mcp.setup_tool._download_local_embedding") as mock_embed,
        patch("wet_mcp.setup_tool._download_local_reranker") as mock_rerank,
    ):
        mock_settings.setup_providers.return_value = "local"
        mock_embed.return_value = {"step": "local_embedding", "status": "ok"}
        mock_rerank.return_value = {"step": "local_reranker", "status": "ok"}

        result = await setup_tool_mod.run_warmup()

        assert result["status"] == "ok"
        assert result["mode"] == "local"
        assert len(result["steps"]) == 3  # auto_setup, local_embedding, local_reranker
        assert any(s["step"] == "auto_setup" for s in result["steps"])
