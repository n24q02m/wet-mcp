import sys
import unittest.mock


def test_key_gating_includes_cloud_model_when_key_set(monkeypatch):
    monkeypatch.setenv("EMBEDDING_MODELS", "jina_ai/jina-embeddings-v5-text-small")
    monkeypatch.setenv("JINA_AI_API_KEY", "k")
    from wet_mcp.config import Settings

    assert Settings().embedding_chain() == ["jina_ai/jina-embeddings-v5-text-small"]


def test_key_gating_filters_chain_without_key(monkeypatch):
    monkeypatch.delenv("EMBEDDING_MODELS", raising=False)
    for k in (
        "JINA_AI_API_KEY",
        "GEMINI_API_KEY",
        "GOOGLE_API_KEY",
        "OPENAI_API_KEY",
        "COHERE_API_KEY",
    ):
        monkeypatch.delenv(k, raising=False)
    from wet_mcp.config import Settings

    assert Settings().embedding_chain() == []


def test_cloud_config_no_local_model_download(monkeypatch):
    monkeypatch.setenv("EMBEDDING_MODELS", "jina_ai/jina-embeddings-v5-text-small")
    monkeypatch.setenv("JINA_AI_API_KEY", "k")
    fake_qwen = unittest.mock.MagicMock()
    monkeypatch.setitem(sys.modules, "qwen3_embed", fake_qwen)
    from wet_mcp.config import Settings

    s = Settings()
    assert s.resolve_embedding_backend() == "cloud"
    fake_qwen.assert_not_called()
