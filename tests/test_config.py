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


def test_setup_api_keys_aliases():
    """Test that GOOGLE_API_KEY is aliased to GEMINI_API_KEY."""
    settings = Settings(api_keys=SecretStr("GOOGLE_API_KEY:google-key"))

    with mock.patch.dict(os.environ, {}, clear=True):
        keys = settings.setup_api_keys()
        assert os.environ["GOOGLE_API_KEY"] == "google-key"
        assert os.environ["GEMINI_API_KEY"] == "google-key"
        assert keys["GOOGLE_API_KEY"] == ["google-key"]


def test_setup_api_keys_alias_no_overwrite():
    """Test that alias is not overwritten if already in environment."""
    settings = Settings(api_keys=SecretStr("GOOGLE_API_KEY:new-key"))

    with mock.patch.dict(os.environ, {"GEMINI_API_KEY": "existing-key"}, clear=True):
        settings.setup_api_keys()
        assert os.environ["GOOGLE_API_KEY"] == "new-key"
        assert os.environ["GEMINI_API_KEY"] == "existing-key"


def test_setup_api_keys_complex_whitespace():
    """Test complex whitespace and empty parts."""
    settings = Settings(api_keys=SecretStr("  KEY1 : val1 , , KEY2:val2  , KEY3:  "))

    with mock.patch.dict(os.environ, {}, clear=True):
        keys = settings.setup_api_keys()
        assert keys == {"KEY1": ["val1"], "KEY2": ["val2"]}
        assert os.environ["KEY1"] == "val1"
        assert os.environ["KEY2"] == "val2"
        assert "KEY3" not in os.environ


# -----------------------------------------------------------------------
# Embedding backend resolution
# -----------------------------------------------------------------------


def test_resolve_embedding_backend_explicit():
    """Deprecated EMBEDDING_BACKEND is still honored (one release)."""
    settings = Settings(embedding_backend="cloud")
    assert settings.resolve_embedding_backend() == "cloud"


def test_resolve_embedding_backend_local_auto():
    """Inferred 'local' when chain is empty (no keys)."""
    settings = Settings(embedding_backend="", embedding_models="")
    with mock.patch.dict(os.environ, {}, clear=True):
        assert settings.resolve_embedding_backend() == "local"


def test_resolve_embedding_backend_cloud_auto():
    """Inferred 'cloud' when an explicit chain is set."""
    settings = Settings(
        embedding_backend="",
        embedding_models="gemini/gemini-embedding-001",
    )
    assert settings.resolve_embedding_backend() == "cloud"


def test_resolve_embedding_backend_none():
    """Returns 'local' when chain is empty and no keys."""
    settings = Settings(embedding_backend="", api_keys=None)
    with mock.patch.dict(os.environ, {}, clear=True):
        result = settings.resolve_embedding_backend()
        assert result == "local"


# -----------------------------------------------------------------------
# Reranking backend resolution
# -----------------------------------------------------------------------


def test_resolve_rerank_backend_disabled():
    """Returns empty string when reranking is disabled."""
    settings = Settings(rerank_enabled=False)
    assert settings.resolve_rerank_backend() == ""


def test_resolve_rerank_backend_explicit():
    """Deprecated RERANK_BACKEND is still honored (one release)."""
    settings = Settings(rerank_backend="cloud", rerank_enabled=True)
    assert settings.resolve_rerank_backend() == "cloud"


def test_resolve_rerank_backend_local_when_empty():
    """Inferred 'local' when rerank chain is empty (no keys)."""
    settings = Settings(
        rerank_backend="",
        rerank_models="",
        rerank_enabled=True,
    )
    for v in ("JINA_AI_API_KEY", "COHERE_API_KEY"):
        os.environ.pop(v, None)
    with mock.patch.dict(os.environ, {}, clear=True):
        assert settings.resolve_rerank_backend() == "local"


# -----------------------------------------------------------------------
# Disable-local toggle (DISABLE_LOCAL_EMBED / DISABLE_LOCAL_RERANK)
# 3-way resolution truth table — the conflation fix.
# -----------------------------------------------------------------------


def test_embedding_unavailable_when_local_disabled_and_no_chain():
    """DISABLE_LOCAL_EMBED + empty chain -> 'unavailable' (NOT forced to a model)."""
    settings = Settings(
        embedding_backend="", embedding_models="", disable_local_embed=True
    )
    with mock.patch.dict(os.environ, {}, clear=True):
        assert settings.resolve_embedding_backend() == "unavailable"


def test_embedding_cloud_wins_even_when_local_disabled():
    """A configured cloud chain still resolves to 'cloud' with local disabled."""
    settings = Settings(
        embedding_backend="",
        embedding_models="gemini/gemini-embedding-001",
        disable_local_embed=True,
    )
    assert settings.resolve_embedding_backend() == "cloud"


def test_embedding_local_when_toggle_off_and_no_chain():
    """Toggle off (default) + empty chain -> 'local' (unchanged behaviour)."""
    settings = Settings(
        embedding_backend="", embedding_models="", disable_local_embed=False
    )
    with mock.patch.dict(os.environ, {}, clear=True):
        assert settings.resolve_embedding_backend() == "local"


def test_rerank_unavailable_when_local_disabled_and_no_chain():
    """DISABLE_LOCAL_RERANK + empty chain (rerank enabled) -> 'unavailable'."""
    settings = Settings(
        rerank_enabled=True,
        rerank_backend="",
        rerank_models="",
        disable_local_rerank=True,
    )
    with mock.patch.dict(os.environ, {}, clear=True):
        assert settings.resolve_rerank_backend() == "unavailable"


def test_rerank_disabled_overrides_toggle():
    """rerank_enabled=False still wins -> '' even with the toggle set."""
    settings = Settings(rerank_enabled=False, disable_local_rerank=True)
    assert settings.resolve_rerank_backend() == ""


def test_auto_searxng_enabled_default():
    """Default: auto-spawn local SearXNG enabled."""
    assert (
        Settings(
            wet_auto_searxng=True, disable_local_search=False
        ).auto_searxng_enabled()
        is True
    )


def test_disable_local_search_suppresses_auto_spawn():
    """DISABLE_LOCAL_SEARCH suppresses the auto-spawn even with WET_AUTO_SEARXNG on."""
    assert (
        Settings(
            wet_auto_searxng=True, disable_local_search=True
        ).auto_searxng_enabled()
        is False
    )


def test_auto_searxng_disabled_when_wet_auto_off():
    assert (
        Settings(
            wet_auto_searxng=False, disable_local_search=False
        ).auto_searxng_enabled()
        is False
    )


def test_embed_and_rerank_toggles_are_independent():
    """A user may disable local embed but keep local rerank (and vice versa)."""
    settings = Settings(
        embedding_backend="",
        embedding_models="",
        rerank_backend="",
        rerank_models="",
        rerank_enabled=True,
        disable_local_embed=True,
        disable_local_rerank=False,
    )
    with mock.patch.dict(os.environ, {}, clear=True):
        assert settings.resolve_embedding_backend() == "unavailable"
        assert settings.resolve_rerank_backend() == "local"


# -----------------------------------------------------------------------
# Embedding model resolution
# -----------------------------------------------------------------------


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
# resolve_rerank_backend: chain-inferred + disabled
# -----------------------------------------------------------------------


def test_resolve_rerank_backend_rerank_model_set():
    """Deprecated rerank_model folds into the chain -> 'cloud'."""
    settings = Settings(
        rerank_enabled=True,
        rerank_backend="",
        rerank_model="cohere/rerank-v3",
    )
    assert settings.resolve_rerank_backend() == "cloud"


def test_resolve_rerank_backend_explicit_chain_cloud():
    """Explicit RERANK_MODELS chain -> 'cloud'."""
    settings = Settings(
        rerank_enabled=True,
        rerank_backend="",
        rerank_models="cohere/rerank-v3.5",
    )
    assert settings.resolve_rerank_backend() == "cloud"


def test_resolve_rerank_backend_local_fallback():
    """Returns 'local' when no rerank provider key / chain configured."""
    settings = Settings(
        rerank_enabled=True,
        rerank_backend="",
        rerank_models="",
        api_keys=None,
    )
    with mock.patch.dict(os.environ, {}, clear=True):
        os.environ.pop("COHERE_API_KEY", None)
        assert settings.resolve_rerank_backend() == "local"


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


# -----------------------------------------------------------------------
# BYO local model override (LOCAL_EMBEDDING_MODEL / LOCAL_RERANK_MODEL)
# -----------------------------------------------------------------------


def test_local_embedding_model_override(monkeypatch):
    monkeypatch.setenv("LOCAL_EMBEDDING_MODEL", "Org/custom-embed")
    s = Settings()
    assert s.resolve_local_embedding_model() == "Org/custom-embed"


def test_local_rerank_model_override(monkeypatch):
    monkeypatch.setenv("LOCAL_RERANK_MODEL", "Org/custom-rerank")
    s = Settings()
    assert s.resolve_local_rerank_model() == "Org/custom-rerank"


# -----------------------------------------------------------------------
# Per-task model chains (model-chain migration, 2026-06-11)
# -----------------------------------------------------------------------


def test_wet_embedding_chain_explicit(monkeypatch):
    monkeypatch.setenv(
        "EMBEDDING_MODELS",
        "jina_ai/jina-embeddings-v5-text-small,gemini/gemini-embedding-001",
    )
    s = Settings()
    assert s.embedding_chain()[0] == "jina_ai/jina-embeddings-v5-text-small"
    assert s.resolve_embedding_backend() == "cloud"


def test_wet_embedding_empty_local(monkeypatch):
    for v in (
        "EMBEDDING_MODELS",
        "EMBEDDING_MODEL",
        "JINA_AI_API_KEY",
        "GEMINI_API_KEY",
        "GOOGLE_API_KEY",
        "OPENAI_API_KEY",
        "COHERE_API_KEY",
    ):
        monkeypatch.delenv(v, raising=False)
    assert Settings().embedding_chain() == []
    assert Settings().resolve_embedding_backend() == "local"


def test_wet_rerank_openai_only_is_local(monkeypatch):
    for v in ("RERANK_MODELS", "RERANK_MODEL", "JINA_AI_API_KEY", "COHERE_API_KEY"):
        monkeypatch.delenv(v, raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-x")
    assert Settings().rerank_chain() == []  # no jina/cohere key -> empty -> local
    assert Settings().resolve_rerank_backend() == "local"


def test_wet_llm_chain_default(monkeypatch):
    # Empty LLM_MODELS -> key-gated curated default: only models whose provider
    # key is configured. With the Gemini key the chain head is the gemini
    # default; with no key the chain is empty (LLM off, no keyless cloud model).
    monkeypatch.delenv("LLM_MODELS", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    assert Settings().llm_chain()[0] == "gemini/gemini-3-flash-preview"
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    assert Settings().llm_chain() == []


def test_wet_embedding_primary(monkeypatch):
    monkeypatch.setenv("EMBEDDING_MODELS", "cohere/embed-multilingual-v3.0")
    assert Settings().embedding_primary() == "cohere/embed-multilingual-v3.0"


def test_wet_rerank_primary(monkeypatch):
    monkeypatch.setenv("RERANK_MODELS", "jina_ai/jina-reranker-v3,cohere/rerank-v3.5")
    assert Settings().rerank_primary() == "jina_ai/jina-reranker-v3"


def test_wet_rerank_chain_disabled():
    s = Settings(rerank_enabled=False, rerank_models="cohere/rerank-v3.5")
    assert s.rerank_chain() == []
    assert s.resolve_rerank_backend() == ""


def test_wet_default_chain_filters_to_configured_keys(monkeypatch):
    for v in (
        "EMBEDDING_MODELS",
        "EMBEDDING_MODEL",
        "JINA_AI_API_KEY",
        "GEMINI_API_KEY",
        "GOOGLE_API_KEY",
        "OPENAI_API_KEY",
        "COHERE_API_KEY",
    ):
        monkeypatch.delenv(v, raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "x")
    # Default chain filtered to providers with a configured key.
    assert Settings().embedding_chain() == ["gemini/gemini-embedding-001"]


def test_wet_google_alias_satisfies_gemini(monkeypatch):
    for v in (
        "EMBEDDING_MODELS",
        "EMBEDDING_MODEL",
        "JINA_AI_API_KEY",
        "GEMINI_API_KEY",
        "OPENAI_API_KEY",
        "COHERE_API_KEY",
    ):
        monkeypatch.delenv(v, raising=False)
    monkeypatch.setenv("GOOGLE_API_KEY", "x")
    # GOOGLE_API_KEY alias satisfies GEMINI_API_KEY for the gemini default.
    assert "gemini/gemini-embedding-001" in Settings().embedding_chain()
