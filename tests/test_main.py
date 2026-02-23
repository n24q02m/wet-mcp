"""Tests for wet_mcp.__main__ — CLI dispatcher and warmup."""

import sys
from unittest.mock import MagicMock, patch

import numpy as np


class TestCli:
    """CLI dispatcher routes subcommands correctly."""

    @patch("wet_mcp.server.main")
    def test_default_runs_server(self, mock_main):
        from wet_mcp.__main__ import _cli

        with patch.object(sys, "argv", ["wet-mcp"]):
            _cli()
        mock_main.assert_called_once()

    @patch("wet_mcp.server.main")
    def test_unknown_arg_runs_server(self, mock_main):
        from wet_mcp.__main__ import _cli

        with patch.object(sys, "argv", ["wet-mcp", "--help"]):
            _cli()
        mock_main.assert_called_once()

    def test_warmup_subcommand(self):
        with patch("wet_mcp.__main__._warmup") as mock_warmup:
            from wet_mcp.__main__ import _cli

            with patch.object(sys, "argv", ["wet-mcp", "warmup"]):
                _cli()
            mock_warmup.assert_called_once()

    def test_setup_sync_subcommand_with_remote(self):
        with patch("wet_mcp.sync.setup_sync") as mock_setup:
            from wet_mcp.__main__ import _cli

            with patch.object(sys, "argv", ["wet-mcp", "setup-sync", "gdrive"]):
                _cli()
            mock_setup.assert_called_once_with("gdrive")

    def test_setup_sync_default_remote_type(self):
        with patch("wet_mcp.sync.setup_sync") as mock_setup:
            from wet_mcp.__main__ import _cli

            with patch.object(sys, "argv", ["wet-mcp", "setup-sync"]):
                _cli()
            mock_setup.assert_called_once_with("drive")


class TestClearModelCache:
    """_clear_model_cache removes corrupted HF Hub cache directories."""

    def test_removes_existing_cache(self, tmp_path):
        from wet_mcp.__main__ import _clear_model_cache

        model_dir = tmp_path / "models--org--model"
        model_dir.mkdir(parents=True)
        (model_dir / "refs").mkdir()
        (model_dir / "blobs").mkdir()
        (model_dir / "blobs" / "abc.incomplete").touch()

        with patch.dict("os.environ", {"QWEN3_EMBED_CACHE_PATH": str(tmp_path)}):
            _clear_model_cache("org/model")

        assert not model_dir.exists()

    def test_noop_when_cache_missing(self, tmp_path):
        from wet_mcp.__main__ import _clear_model_cache

        with patch.dict("os.environ", {"QWEN3_EMBED_CACHE_PATH": str(tmp_path)}):
            _clear_model_cache("nonexistent/model")  # Should not raise


class TestWarmupCorruptedCache:
    """_warmup handles corrupted ONNX cache (NO_SUCHFILE) gracefully."""

    @patch("wet_mcp.setup.run_auto_setup")
    @patch("wet_mcp.__main__._clear_model_cache")
    @patch("qwen3_embed.TextEmbedding")
    @patch("wet_mcp.config.settings")
    def test_corrupted_embedding_cache_clears_and_retries(
        self, mock_settings, mock_te, mock_clear, mock_setup
    ):
        """When TextEmbedding raises NO_SUCHFILE, clears cache and retries."""
        from wet_mcp.__main__ import _warmup

        mock_settings.setup_api_keys.return_value = {}
        mock_settings.resolve_local_embedding_model.return_value = "org/embed"
        mock_settings.rerank_enabled = False

        mock_model_ok = MagicMock()
        mock_model_ok.embed.return_value = iter([np.array([0.1, 0.2])])

        exc = Exception("[ONNXRuntimeError] : 3 : NO_SUCHFILE : file doesn't exist")
        mock_te.side_effect = [exc, mock_model_ok]

        _warmup()

        mock_clear.assert_called_once_with("org/embed")
        assert mock_te.call_count == 2

    @patch("wet_mcp.setup.run_auto_setup")
    @patch("wet_mcp.__main__._clear_model_cache")
    @patch("qwen3_embed.TextCrossEncoder")
    @patch("qwen3_embed.TextEmbedding")
    @patch("wet_mcp.config.settings")
    def test_corrupted_reranker_cache_clears_and_retries(
        self, mock_settings, mock_te, mock_tce, mock_clear, mock_setup
    ):
        """When TextCrossEncoder raises NO_SUCHFILE, clears cache and retries."""
        from wet_mcp.__main__ import _warmup

        mock_settings.setup_api_keys.return_value = {}
        mock_settings.resolve_local_embedding_model.return_value = "org/embed"
        mock_settings.resolve_local_rerank_model.return_value = "org/rerank"
        mock_settings.rerank_enabled = True

        # Embedding succeeds
        mock_embed = MagicMock()
        mock_embed.embed.return_value = iter([np.array([0.1])])
        mock_te.return_value = mock_embed

        # Reranker: first call raises, second succeeds
        mock_reranker_ok = MagicMock()
        mock_reranker_ok.rerank.return_value = iter([0.9])
        exc = Exception("[ONNXRuntimeError] : 3 : NO_SUCHFILE : file doesn't exist")
        mock_tce.side_effect = [exc, mock_reranker_ok]

        _warmup()

        mock_clear.assert_called_once_with("org/rerank")
        assert mock_tce.call_count == 2

    @patch("wet_mcp.setup.run_auto_setup")
    @patch("qwen3_embed.TextEmbedding")
    @patch("wet_mcp.config.settings")
    def test_non_cache_error_re_raises(self, mock_settings, mock_te, mock_setup):
        """Non-cache errors (e.g. import error) are re-raised."""
        from wet_mcp.__main__ import _warmup

        mock_settings.setup_api_keys.return_value = {}
        mock_settings.resolve_local_embedding_model.return_value = "org/model"
        mock_settings.rerank_enabled = False

        mock_te.side_effect = ImportError("qwen3_embed not installed")

        import pytest

        with pytest.raises(ImportError, match="not installed"):
            _warmup()


class TestWarmup:
    """_warmup() pre-downloads models or validates cloud models."""

    @patch("wet_mcp.setup.run_auto_setup")
    @patch("wet_mcp.server._EMBEDDING_CANDIDATES", ["gemini/embed-1"])
    @patch("wet_mcp.embedder.init_backend")
    @patch("wet_mcp.config.settings")
    def test_cloud_embedding_and_reranker_success(
        self, mock_settings, mock_init, mock_setup
    ):
        """When cloud embedding + reranker work, skip local downloads."""
        from wet_mcp.__main__ import _warmup

        mock_settings.setup_api_keys.return_value = {"GEMINI_API_KEY": "k"}
        mock_settings.resolve_embedding_model.return_value = None
        mock_settings.resolve_rerank_model.return_value = "cohere/rerank"

        mock_backend = MagicMock()
        mock_backend.check_available.return_value = 768
        mock_init.return_value = mock_backend

        with patch("wet_mcp.reranker.init_reranker") as mock_rr_init:
            mock_reranker = MagicMock()
            mock_reranker.check_available.return_value = True
            mock_rr_init.return_value = mock_reranker

            _warmup()

        mock_setup.assert_called_once()
        mock_init.assert_called_once_with("litellm", "gemini/embed-1")

    @patch("wet_mcp.setup.run_auto_setup")
    @patch("qwen3_embed.TextEmbedding")
    @patch("wet_mcp.config.settings")
    def test_no_api_keys_downloads_local_embedding(
        self, mock_settings, mock_te, mock_setup
    ):
        """Without API keys, downloads local embedding model."""
        from wet_mcp.__main__ import _warmup

        mock_settings.setup_api_keys.return_value = {}
        mock_settings.resolve_local_embedding_model.return_value = "local/embed"
        mock_settings.rerank_enabled = False

        mock_model = MagicMock()
        mock_model.embed.return_value = iter([np.array([0.1, 0.2])])
        mock_te.return_value = mock_model

        _warmup()

        mock_setup.assert_called_once()
        mock_te.assert_called_once_with(model_name="local/embed")

    @patch("wet_mcp.setup.run_auto_setup")
    @patch("qwen3_embed.TextCrossEncoder")
    @patch("qwen3_embed.TextEmbedding")
    @patch("wet_mcp.config.settings")
    def test_local_embedding_and_reranker(
        self, mock_settings, mock_te, mock_tce, mock_setup
    ):
        """Downloads both local embedding and reranker when rerank_enabled."""
        from wet_mcp.__main__ import _warmup

        mock_settings.setup_api_keys.return_value = {}
        mock_settings.resolve_local_embedding_model.return_value = "local/embed"
        mock_settings.resolve_local_rerank_model.return_value = "local/rerank"
        mock_settings.rerank_enabled = True

        mock_embed_model = MagicMock()
        mock_embed_model.embed.return_value = iter([np.array([0.1])])
        mock_te.return_value = mock_embed_model

        mock_rerank_model = MagicMock()
        mock_rerank_model.rerank.return_value = iter([0.9])
        mock_tce.return_value = mock_rerank_model

        _warmup()

        mock_te.assert_called_once()
        mock_tce.assert_called_once_with(model_name="local/rerank")

    @patch("wet_mcp.setup.run_auto_setup")
    @patch("qwen3_embed.TextEmbedding")
    @patch("wet_mcp.config.settings")
    def test_rerank_disabled_skips_reranker(self, mock_settings, mock_te, mock_setup):
        """When rerank_enabled=False, skips reranker download."""
        from wet_mcp.__main__ import _warmup

        mock_settings.setup_api_keys.return_value = {}
        mock_settings.resolve_local_embedding_model.return_value = "local/embed"
        mock_settings.rerank_enabled = False

        mock_model = MagicMock()
        mock_model.embed.return_value = iter([np.array([0.1])])
        mock_te.return_value = mock_model

        _warmup()

        # TextCrossEncoder should not be imported/called
        mock_te.assert_called_once()

    @patch("wet_mcp.setup.run_auto_setup")
    @patch("qwen3_embed.TextEmbedding")
    @patch("wet_mcp.server._EMBEDDING_CANDIDATES", ["model-a"])
    @patch("wet_mcp.embedder.init_backend")
    @patch("wet_mcp.config.settings")
    def test_cloud_embedding_fail_falls_back_to_local(
        self, mock_settings, mock_init, mock_te, mock_setup
    ):
        """When cloud embedding fails, falls back to local download."""
        from wet_mcp.__main__ import _warmup

        mock_settings.setup_api_keys.return_value = {"KEY": "val"}
        mock_settings.resolve_embedding_model.return_value = None
        mock_settings.resolve_local_embedding_model.return_value = "local/m"
        mock_settings.rerank_enabled = False

        mock_backend = MagicMock()
        mock_backend.check_available.return_value = 0
        mock_init.return_value = mock_backend

        mock_model = MagicMock()
        mock_model.embed.return_value = iter([np.array([0.1])])
        mock_te.return_value = mock_model

        _warmup()

        mock_te.assert_called_once_with(model_name="local/m")

    @patch("wet_mcp.setup.run_auto_setup")
    @patch("wet_mcp.server._EMBEDDING_CANDIDATES", ["gemini/embed"])
    @patch("wet_mcp.embedder.init_backend")
    @patch("wet_mcp.config.settings")
    def test_cloud_ok_but_reranker_fail_still_succeeds(
        self, mock_settings, mock_init, mock_setup
    ):
        """When cloud embedding works but reranker fails, still succeeds."""
        from wet_mcp.__main__ import _warmup

        mock_settings.setup_api_keys.return_value = {"KEY": "val"}
        mock_settings.resolve_embedding_model.return_value = None
        mock_settings.resolve_rerank_model.return_value = "cohere/rerank"

        mock_backend = MagicMock()
        mock_backend.check_available.return_value = 768
        mock_init.return_value = mock_backend

        with patch("wet_mcp.reranker.init_reranker") as mock_rr_init:
            mock_reranker = MagicMock()
            mock_reranker.check_available.return_value = False
            mock_rr_init.return_value = mock_reranker

            _warmup()  # Should not raise

    @patch("wet_mcp.setup.run_auto_setup")
    @patch("wet_mcp.server._EMBEDDING_CANDIDATES", ["model-a"])
    @patch("wet_mcp.embedder.init_backend")
    @patch("wet_mcp.config.settings")
    def test_cloud_exception_falls_back(self, mock_settings, mock_init, mock_setup):
        """When init_backend raises, catches exception and falls back."""
        from wet_mcp.__main__ import _warmup

        mock_settings.setup_api_keys.return_value = {"KEY": "val"}
        mock_settings.resolve_embedding_model.return_value = None
        mock_settings.resolve_local_embedding_model.return_value = "local/m"
        mock_settings.rerank_enabled = False

        mock_init.side_effect = Exception("init failed")

        with patch("qwen3_embed.TextEmbedding") as mock_te:
            mock_model = MagicMock()
            mock_model.embed.return_value = iter([np.array([0.1])])
            mock_te.return_value = mock_model

            _warmup()

            mock_te.assert_called_once()

    @patch("wet_mcp.setup.run_auto_setup")
    @patch("wet_mcp.server._EMBEDDING_CANDIDATES", ["gemini/embed"])
    @patch("wet_mcp.embedder.init_backend")
    @patch("wet_mcp.config.settings")
    def test_explicit_model_tried_first(self, mock_settings, mock_init, mock_setup):
        """When EMBEDDING_MODEL is set, uses that instead of candidates."""
        from wet_mcp.__main__ import _warmup

        mock_settings.setup_api_keys.return_value = {"KEY": "val"}
        mock_settings.resolve_embedding_model.return_value = "explicit/model"
        mock_settings.resolve_rerank_model.return_value = None

        mock_backend = MagicMock()
        mock_backend.check_available.return_value = 512
        mock_init.return_value = mock_backend

        _warmup()

        mock_init.assert_called_once_with("litellm", "explicit/model")

    @patch("wet_mcp.setup.run_auto_setup")
    @patch("wet_mcp.server._EMBEDDING_CANDIDATES", ["gemini/embed"])
    @patch("wet_mcp.embedder.init_backend")
    @patch("wet_mcp.config.settings")
    def test_no_rerank_model_skips_reranker_check(
        self, mock_settings, mock_init, mock_setup
    ):
        """When resolve_rerank_model returns None, skip reranker validation."""
        from wet_mcp.__main__ import _warmup

        mock_settings.setup_api_keys.return_value = {"KEY": "val"}
        mock_settings.resolve_embedding_model.return_value = None
        mock_settings.resolve_rerank_model.return_value = None

        mock_backend = MagicMock()
        mock_backend.check_available.return_value = 768
        mock_init.return_value = mock_backend

        _warmup()  # Should complete without error
