import os
from unittest import mock

from pydantic import SecretStr

from wet_mcp.config import Settings


def test_setup_api_keys_valid():
    """Test setup_api_keys with valid input."""
    settings = Settings(api_keys=SecretStr("GOOGLE_API_KEY:abc,OPENAI_API_KEY:xyz"))

    with mock.patch.dict(os.environ, {}, clear=True):
        keys = settings.setup_api_keys()

        assert keys == {"GOOGLE_API_KEY": ["abc"], "OPENAI_API_KEY": ["xyz"]}

        assert os.environ["GOOGLE_API_KEY"] == "abc"
        assert os.environ["OPENAI_API_KEY"] == "xyz"


def test_setup_api_keys_empty():
    """Test setup_api_keys with empty input."""
    settings_none = Settings(api_keys=None)
    with mock.patch.dict(os.environ, {}, clear=True):
        assert settings_none.setup_api_keys() == {}
        assert len(os.environ) == 0

    settings_empty = Settings(api_keys=SecretStr(""))
    with mock.patch.dict(os.environ, {}, clear=True):
        assert settings_empty.setup_api_keys() == {}
        assert len(os.environ) == 0


def test_setup_api_keys_invalid_format():
    """Test setup_api_keys with invalid format strings."""
    settings = Settings(api_keys=SecretStr("INVALID_KEY,VALID:key"))

    with mock.patch.dict(os.environ, {}, clear=True):
        keys = settings.setup_api_keys()

        assert keys == {"VALID": ["key"]}
        assert os.environ.get("INVALID_KEY") is None
        assert os.environ["VALID"] == "key"

    settings = Settings(api_keys=SecretStr("ENV:,VALID:key"))
    with mock.patch.dict(os.environ, {}, clear=True):
        keys = settings.setup_api_keys()
        assert keys == {"VALID": ["key"]}
        assert os.environ.get("ENV") is None


def test_setup_api_keys_multiple_keys():
    """Test setup_api_keys with multiple keys for same env var."""
    settings = Settings(api_keys=SecretStr("ENV:key1,ENV:key2"))

    with mock.patch.dict(os.environ, {}, clear=True):
        keys = settings.setup_api_keys()

        assert keys == {"ENV": ["key1", "key2"]}

        assert os.environ["ENV"] == "key1"


def test_setup_api_keys_whitespace():
    """Test setup_api_keys with whitespace around keys."""
    settings = Settings(api_keys=SecretStr(" ENV : key1 , OTHER : key2 "))

    with mock.patch.dict(os.environ, {}, clear=True):
        keys = settings.setup_api_keys()

        assert keys == {"ENV": ["key1"], "OTHER": ["key2"]}
        assert os.environ["ENV"] == "key1"
        assert os.environ["OTHER"] == "key2"


# -----------------------------------------------------------------------
# Embedding backend resolution
# -----------------------------------------------------------------------


def test_resolve_embedding_backend_explicit():
    """Explicit EMBEDDING_BACKEND is returned as-is."""
    settings = Settings(embedding_backend="cloud")
    assert settings.resolve_embedding_backend() == "cloud"


def test_resolve_embedding_backend_local_auto():
    """Auto-detect returns 'local' when qwen3-embed is importable."""
    settings = Settings(embedding_backend="")
    with mock.patch.dict("sys.modules", {"qwen3_embed": mock.MagicMock()}):
        assert settings.resolve_embedding_backend() == "local"


def test_resolve_embedding_backend_cloud_auto():
    """Auto-detect returns 'cloud' when API keys are set."""
    settings = Settings(embedding_backend="", api_keys=SecretStr("GOOGLE_API_KEY:abc"))
    result = settings.resolve_embedding_backend()
    assert result == "cloud"


def test_resolve_embedding_backend_none():
    """Returns 'local' when no backend is available and no keys."""
    settings = Settings(embedding_backend="", api_keys=None)
    with mock.patch.dict(os.environ, {}, clear=True):
        result = settings.resolve_embedding_backend()
        assert isinstance(result, str)


# -----------------------------------------------------------------------
# Reranking backend resolution
# -----------------------------------------------------------------------


def test_resolve_rerank_backend_disabled():
    """Returns empty string when reranking is disabled."""
    settings = Settings(rerank_enabled=False)
    assert settings.resolve_rerank_backend() == ""


def test_resolve_rerank_backend_explicit():
    """Explicit RERANK_BACKEND is returned as-is."""
    settings = Settings(rerank_backend="cloud", rerank_enabled=True)
    assert settings.resolve_rerank_backend() == "cloud"


def test_resolve_rerank_backend_follows_embedding():
    """Rerank backend follows embedding backend when not explicit."""
    settings = Settings(
        embedding_backend="local",
        rerank_backend="",
        rerank_enabled=True,
    )
    with mock.patch.dict("sys.modules", {"qwen3_embed": mock.MagicMock()}):
        assert settings.resolve_rerank_backend() == "local"


# -----------------------------------------------------------------------
# Embedding model resolution
# -----------------------------------------------------------------------


def test_resolve_embedding_model_explicit():
    """Explicit EMBEDDING_MODEL is returned."""
    settings = Settings(embedding_model="gemini/gemini-embedding-2-preview")
    assert settings.resolve_embedding_model() == "gemini/gemini-embedding-2-preview"


def test_resolve_embedding_model_auto():
    """Returns None for auto-detection when no explicit model."""
    settings = Settings(embedding_model="")
    assert settings.resolve_embedding_model() is None


def test_resolve_embedding_dims():
    """Returns explicit dims or 0 for auto-detect."""
    assert Settings(embedding_dims=768).resolve_embedding_dims() == 768
    assert Settings(embedding_dims=0).resolve_embedding_dims() == 0


# -----------------------------------------------------------------------
# Path helpers: get_data_dir / get_db_path with custom paths
# -----------------------------------------------------------------------


def test_get_data_dir_custom_cache_dir(tmp_path):
    """get_data_dir returns custom cache_dir when set."""
    settings = Settings(cache_dir=str(tmp_path / "custom"))
    assert settings.get_data_dir() == tmp_path / "custom"


def test_get_data_dir_default():
    """get_data_dir returns ~/.wet-mcp when cache_dir is empty."""
    from pathlib import Path

    settings = Settings(cache_dir="")
    assert settings.get_data_dir() == Path.home() / ".wet-mcp"


def test_get_db_path_custom_docs_db_path(tmp_path):
    """get_db_path returns custom docs_db_path when set."""
    custom = tmp_path / "my_docs.db"
    settings = Settings(docs_db_path=str(custom))
    assert settings.get_db_path() == custom


def test_get_db_path_default():
    """get_db_path returns get_data_dir()/docs.db when docs_db_path is empty."""
    settings = Settings(docs_db_path="")
    assert settings.get_db_path() == settings.get_data_dir() / "docs.db"


# -----------------------------------------------------------------------
# setup_api_keys with @file_path format
# -----------------------------------------------------------------------


def test_setup_api_keys_file_path(tmp_path):
    """setup_api_keys reads keys from a file when using @path format."""
    keys_file = tmp_path / "keys.txt"
    keys_file.write_text("GOOGLE_API_KEY:file_key1\nOPENAI_API_KEY:file_key2")

    settings = Settings(api_keys=SecretStr(f"@{keys_file}"))

    with mock.patch.dict(os.environ, {}, clear=True):
        keys = settings.setup_api_keys()

        assert keys == {
            "GOOGLE_API_KEY": ["file_key1"],
            "OPENAI_API_KEY": ["file_key2"],
        }
        assert os.environ["GOOGLE_API_KEY"] == "file_key1"
        assert os.environ["OPENAI_API_KEY"] == "file_key2"


def test_setup_api_keys_file_not_found():
    """setup_api_keys raises FileNotFoundError for missing file."""
    settings = Settings(api_keys=SecretStr("@/nonexistent/keys.txt"))

    import pytest

    with pytest.raises(FileNotFoundError, match="API keys file not found"):
        settings.setup_api_keys()


def test_setup_api_keys_file_read_error(tmp_path):
    """setup_api_keys raises ValueError when file read fails."""
    import pytest

    keys_file = tmp_path / "keys.txt"
    keys_file.write_text("dummy")

    settings = Settings(api_keys=SecretStr(f"@{keys_file}"))

    # Mock path.read_text to raise an exception
    with mock.patch(
        "wet_mcp.config.Path.read_text", side_effect=PermissionError("denied")
    ):
        with pytest.raises(ValueError, match="Failed to read API keys file"):
            settings.setup_api_keys()


# -----------------------------------------------------------------------
# resolve_rerank_backend: rerank_model, env var, api_keys detection
# -----------------------------------------------------------------------


def test_resolve_rerank_backend_rerank_model_set():
    """Returns 'cloud' when rerank_model is explicitly set."""
    settings = Settings(
        rerank_enabled=True,
        rerank_backend="",
        rerank_model="cohere/rerank-v3",
    )
    assert settings.resolve_rerank_backend() == "cloud"


def test_resolve_rerank_backend_env_var_detection():
    """Returns 'cloud' when COHERE_API_KEY is in env."""
    settings = Settings(
        rerank_enabled=True,
        rerank_backend="",
        api_keys=None,
    )
    with mock.patch.dict(os.environ, {"COHERE_API_KEY": "test-key"}, clear=False):
        assert settings.resolve_rerank_backend() == "cloud"


def test_resolve_rerank_backend_api_keys_cohere():
    """Returns 'cloud' when API_KEYS contains COHERE_API_KEY."""
    settings = Settings(
        rerank_enabled=True,
        rerank_backend="",
        api_keys=SecretStr("COHERE_API_KEY:test"),
    )
    with mock.patch.dict(os.environ, {}, clear=True):
        assert settings.resolve_rerank_backend() == "cloud"


def test_resolve_rerank_backend_local_fallback():
    """Returns 'local' when no rerank provider is detected."""
    settings = Settings(
        rerank_enabled=True,
        rerank_backend="",
        api_keys=None,
    )
    with mock.patch.dict(os.environ, {}, clear=True):
        # Remove COHERE_API_KEY if present
        os.environ.pop("COHERE_API_KEY", None)
        assert settings.resolve_rerank_backend() == "local"


# -----------------------------------------------------------------------
# resolve_rerank_model: auto-detection
# -----------------------------------------------------------------------


def test_resolve_rerank_model_explicit():
    """Returns explicit rerank_model when set."""
    settings = Settings(rerank_model="cohere/custom-model")
    assert settings.resolve_rerank_model() == "cohere/custom-model"


def test_resolve_rerank_model_env_var_auto():
    """Auto-detects model from COHERE_API_KEY env var."""
    settings = Settings(rerank_model="")
    with mock.patch.dict(os.environ, {"COHERE_API_KEY": "test-key"}, clear=False):
        assert settings.resolve_rerank_model() == "cohere/rerank-v4.0-pro"


def test_resolve_rerank_model_api_keys_auto():
    """Auto-detects model from API_KEYS containing COHERE_API_KEY."""
    settings = Settings(
        rerank_model="",
        api_keys=SecretStr("COHERE_API_KEY:test-key"),
    )
    with mock.patch.dict(os.environ, {}, clear=True):
        assert settings.resolve_rerank_model() == "cohere/rerank-v4.0-pro"


def test_resolve_rerank_model_none():
    """Returns None when no rerank provider detected."""
    settings = Settings(rerank_model="", api_keys=None)
    with mock.patch.dict(os.environ, {}, clear=True):
        os.environ.pop("COHERE_API_KEY", None)
        assert settings.resolve_rerank_model() is None


# -----------------------------------------------------------------------
# resolve_provider_mode and setup_providers
# -----------------------------------------------------------------------


def test_resolve_provider_mode_sdk():
    """Returns 'sdk' when api_keys is set."""
    settings = Settings(api_keys=SecretStr("GOOGLE_API_KEY:abc"))
    assert settings.resolve_provider_mode() == "sdk"


def test_resolve_provider_mode_sdk_env():
    """Returns 'sdk' when provider env var is set."""
    settings = Settings(api_keys=None)
    with mock.patch.dict(os.environ, {"GEMINI_API_KEY": "test"}, clear=True):
        assert settings.resolve_provider_mode() == "sdk"


def test_resolve_provider_mode_local():
    """Returns 'local' when no keys configured."""
    settings = Settings(api_keys=None)
    with mock.patch.dict(os.environ, {}, clear=True):
        assert settings.resolve_provider_mode() == "local"


def test_setup_providers_sdk_mode():
    """setup_providers configures SDK mode and calls setup_api_keys."""
    settings = Settings(
        api_keys=SecretStr("GOOGLE_API_KEY:abc"),
    )

    with mock.patch.dict(os.environ, {}, clear=True):
        mode = settings.setup_providers()

        assert mode == "sdk"
        assert os.environ["GOOGLE_API_KEY"] == "abc"


def test_setup_providers_local_mode():
    """setup_providers returns 'local' when no keys configured."""
    settings = Settings(api_keys=None)
    with mock.patch.dict(os.environ, {}, clear=True):
        mode = settings.setup_providers()
    assert mode == "local"


# -----------------------------------------------------------------------
# Additional coverage: helper functions, cache path, local models
# -----------------------------------------------------------------------


def test_get_cache_db_path():
    """get_cache_db_path returns get_data_dir()/cache.db."""
    settings = Settings(cache_dir="/tmp/test-wet")
    assert (
        settings.get_cache_db_path()
        == Settings(cache_dir="/tmp/test-wet").get_data_dir() / "cache.db"
    )


def test_detect_gpu_no_onnxruntime():
    """_detect_gpu returns False when onnxruntime is not available."""
    from wet_mcp.config import _detect_gpu

    with mock.patch.dict("sys.modules", {"onnxruntime": None}):
        assert _detect_gpu() is False


def test_detect_gpu_with_cuda():
    """_detect_gpu returns True when CUDAExecutionProvider is available."""
    from wet_mcp.config import _detect_gpu

    ort_mock = mock.MagicMock()
    ort_mock.get_available_providers.return_value = [
        "CUDAExecutionProvider",
        "CPUExecutionProvider",
    ]
    with mock.patch.dict("sys.modules", {"onnxruntime": ort_mock}):
        assert _detect_gpu() is True


def test_detect_gpu_cpu_only():
    """_detect_gpu returns False with CPU-only providers."""
    from wet_mcp.config import _detect_gpu

    ort_mock = mock.MagicMock()
    ort_mock.get_available_providers.return_value = ["CPUExecutionProvider"]
    with mock.patch.dict("sys.modules", {"onnxruntime": ort_mock}):
        assert _detect_gpu() is False


def test_has_gguf_support_missing():
    """_has_gguf_support returns False when llama_cpp is not installed."""
    from wet_mcp.config import _has_gguf_support

    with mock.patch("importlib.util.find_spec", return_value=None):
        assert _has_gguf_support() is False


def test_has_gguf_support_available():
    """_has_gguf_support returns True when llama_cpp is installed."""
    from wet_mcp.config import _has_gguf_support

    with mock.patch("importlib.util.find_spec", return_value=mock.MagicMock()):
        assert _has_gguf_support() is True


def test_resolve_local_model_onnx_fallback():
    """_resolve_local_model returns ONNX model when no GPU or no GGUF support."""
    from wet_mcp.config import _resolve_local_model

    with mock.patch("wet_mcp.config._detect_gpu", return_value=False):
        assert _resolve_local_model("onnx-model", "gguf-model") == "onnx-model"


def test_resolve_local_model_gguf():
    """_resolve_local_model returns GGUF model when GPU and llama-cpp available."""
    from wet_mcp.config import _resolve_local_model

    with (
        mock.patch("wet_mcp.config._detect_gpu", return_value=True),
        mock.patch("wet_mcp.config._has_gguf_support", return_value=True),
    ):
        assert _resolve_local_model("onnx-model", "gguf-model") == "gguf-model"


def test_resolve_local_embedding_model():
    """resolve_local_embedding_model delegates to _resolve_local_model."""
    settings = Settings()
    with mock.patch(
        "wet_mcp.config._resolve_local_model", return_value="test-model"
    ) as m:
        result = settings.resolve_local_embedding_model()
        assert result == "test-model"
        m.assert_called_once()


def test_resolve_local_rerank_model():
    """resolve_local_rerank_model delegates to _resolve_local_model."""
    settings = Settings()
    with mock.patch(
        "wet_mcp.config._resolve_local_model", return_value="test-rerank"
    ) as m:
        result = settings.resolve_local_rerank_model()
        assert result == "test-rerank"
        m.assert_called_once()


def test_get_config_dir():
    from wet_mcp.config import Settings

    s = Settings(cache_dir="/tmp/test")
    assert str(s.get_config_dir()) == "/tmp/test"
