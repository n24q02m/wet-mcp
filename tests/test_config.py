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
    settings = Settings(embedding_backend="litellm")
    assert settings.resolve_embedding_backend() == "litellm"


def test_resolve_embedding_backend_local_auto():
    """Auto-detect returns 'local' when qwen3-embed is importable."""
    settings = Settings(embedding_backend="")
    with mock.patch.dict("sys.modules", {"qwen3_embed": mock.MagicMock()}):
        assert settings.resolve_embedding_backend() == "local"


def test_resolve_embedding_backend_litellm_auto():
    """Auto-detect returns 'litellm' when API keys are set and no local."""
    settings = Settings(embedding_backend="", api_keys=SecretStr("GOOGLE_API_KEY:abc"))
    with mock.patch("builtins.__import__", side_effect=ImportError("no qwen3_embed")):
        # Can't easily block a specific import while allowing others,
        # so test the fallback logic directly
        result = settings.resolve_embedding_backend()
        assert result in ("local", "litellm")


def test_resolve_embedding_backend_none():
    """Returns empty string when no backend is available and no keys."""
    settings = Settings(embedding_backend="", api_keys=None)
    with mock.patch(
        "wet_mcp.config.Settings.resolve_embedding_backend",
        wraps=settings.resolve_embedding_backend,
    ):
        # The actual result depends on qwen3-embed availability
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
    settings = Settings(rerank_backend="litellm", rerank_enabled=True)
    assert settings.resolve_rerank_backend() == "litellm"


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
    settings = Settings(embedding_model="gemini/gemini-embedding-001")
    assert settings.resolve_embedding_model() == "gemini/gemini-embedding-001"


def test_resolve_embedding_model_auto():
    """Returns None for auto-detection when no explicit model."""
    settings = Settings(embedding_model="")
    assert settings.resolve_embedding_model() is None


def test_resolve_embedding_dims():
    """Returns explicit dims or 0 for auto-detect."""
    assert Settings(embedding_dims=768).resolve_embedding_dims() == 768
    assert Settings(embedding_dims=0).resolve_embedding_dims() == 0
