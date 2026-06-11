"""Tests for wet_mcp.__main__ — CLI entry point and setup_tool functions."""

import sys
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np


class TestCli:
    """CLI dispatcher starts MCP server."""

    @patch("wet_mcp.__main__.main")
    def test_default_runs_server(self, mock_main):
        from wet_mcp.__main__ import _cli

        _cli()
        mock_main.assert_called_once()

    @patch("wet_mcp.__main__.main")
    def test_cli_always_runs_server(self, mock_main):
        """_cli() always starts MCP server (no subcommands)."""
        from wet_mcp.__main__ import _cli

        with patch.object(sys, "argv", ["wet-mcp", "anything"]):
            _cli()
        mock_main.assert_called_once()


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

    @patch("wet_mcp.reranker.init_reranker")
    @patch("wet_mcp.embedder.init_backend")
    async def test_cloud_embedding_and_reranker_success(self, mock_init, mock_rr_init):
        from wet_mcp.setup_tool import _validate_cloud_models

        mock_settings = MagicMock()
        mock_settings.embedding_chain.return_value = ["gemini/embed-1"]
        mock_settings.rerank_chain.return_value = ["cohere/rerank"]

        mock_backend = MagicMock()
        mock_backend.check_available = AsyncMock(return_value=768)
        mock_init.return_value = mock_backend

        mock_reranker = MagicMock()
        mock_reranker.check_available.return_value = True
        mock_rr_init.return_value = mock_reranker

        result = await _validate_cloud_models(mock_settings)

        assert result["cloud_ready"] is True
        assert result["embedding"]["model"] == "gemini/embed-1"
        assert result["reranker"]["model"] == "cohere/rerank"

    @patch("wet_mcp.embedder.init_backend")
    async def test_cloud_embedding_fails(self, mock_init):
        from wet_mcp.setup_tool import _validate_cloud_models

        mock_settings = MagicMock()
        mock_settings.embedding_chain.return_value = ["model-a"]

        mock_backend = MagicMock()
        mock_backend.check_available = AsyncMock(return_value=0)
        mock_init.return_value = mock_backend

        result = await _validate_cloud_models(mock_settings)
        assert result["cloud_ready"] is False

    @patch("wet_mcp.reranker.init_reranker")
    @patch("wet_mcp.embedder.init_backend")
    async def test_cloud_reranker_fails(self, mock_init, mock_rr_init):
        from wet_mcp.setup_tool import _validate_cloud_models

        mock_settings = MagicMock()
        mock_settings.embedding_chain.return_value = ["gemini/embed"]
        mock_settings.rerank_chain.return_value = ["cohere/rerank"]

        mock_backend = MagicMock()
        mock_backend.check_available = AsyncMock(return_value=768)
        mock_init.return_value = mock_backend

        mock_reranker = MagicMock()
        mock_reranker.check_available.return_value = False
        mock_rr_init.return_value = mock_reranker

        result = await _validate_cloud_models(mock_settings)
        assert result["cloud_ready"] is True
        assert result["reranker"] is None

    @patch("wet_mcp.reranker.init_reranker")
    @patch("wet_mcp.embedder.init_backend")
    async def test_cloud_reranker_init_exception(self, mock_init, mock_rr_init):
        from wet_mcp.setup_tool import _validate_cloud_models

        mock_settings = MagicMock()
        mock_settings.embedding_chain.return_value = ["gemini/embed"]
        mock_settings.rerank_chain.return_value = ["cohere/rerank"]

        mock_backend = MagicMock()
        mock_backend.check_available = AsyncMock(return_value=768)
        mock_init.return_value = mock_backend

        mock_rr_init.side_effect = Exception("reranker init failed")

        result = await _validate_cloud_models(mock_settings)
        assert result["cloud_ready"] is True
        assert result["reranker"] is None

    @patch("wet_mcp.embedder.init_backend")
    async def test_explicit_model_tried_first(self, mock_init):
        from wet_mcp.setup_tool import _validate_cloud_models

        mock_settings = MagicMock()
        mock_settings.embedding_chain.return_value = ["explicit/model"]
        mock_settings.rerank_chain.return_value = []

        mock_backend = MagicMock()
        mock_backend.check_available = AsyncMock(return_value=512)
        mock_init.return_value = mock_backend

        result = await _validate_cloud_models(mock_settings)

        mock_init.assert_called_once_with("cloud", "explicit/model")
        assert result["cloud_ready"] is True

    @patch("wet_mcp.embedder.init_backend")
    async def test_no_rerank_model_skips_check(self, mock_init):
        from wet_mcp.setup_tool import _validate_cloud_models

        mock_settings = MagicMock()
        mock_settings.embedding_chain.return_value = ["gemini/embed"]
        mock_settings.rerank_chain.return_value = []

        mock_backend = MagicMock()
        mock_backend.check_available = AsyncMock(return_value=768)
        mock_init.return_value = mock_backend

        result = await _validate_cloud_models(mock_settings)
        assert result["cloud_ready"] is True
        assert result["reranker"] is None

    @patch("wet_mcp.embedder.init_backend")
    async def test_cloud_exception_returns_not_ready(self, mock_init):
        from wet_mcp.setup_tool import _validate_cloud_models

        mock_settings = MagicMock()
        mock_settings.embedding_chain.return_value = ["model-a"]

        mock_init.side_effect = Exception("init failed")

        result = await _validate_cloud_models(mock_settings)
        assert result["cloud_ready"] is False
