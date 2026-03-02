import json
from unittest.mock import MagicMock, patch

import pytest

from wet_mcp import server


@pytest.fixture(autouse=True)
def mock_settings():
    with patch("wet_mcp.server.settings") as mock:
        mock.log_level = "DEBUG"
        mock.tool_timeout = 10
        mock.wet_cache = True
        mock.sync_enabled = False
        mock.sync_remote = ""
        mock.sync_folder = ""
        mock.sync_interval = 3600

        # We also need to mock methods since they are called in `config`
        mock.get_db_path.return_value = "mock_db_path"
        mock.get_cache_db_path.return_value = "mock_cache_path"
        yield mock


@pytest.fixture(autouse=True)
def mock_web_cache():
    server._web_cache = MagicMock()
    server._web_cache.clear = MagicMock()
    yield server._web_cache
    server._web_cache = None


@pytest.fixture(autouse=True)
def mock_docs_db():
    server._docs_db = MagicMock()
    server._docs_db.stats.return_value = {"total_chunks": 100}
    server._docs_db.get_library.return_value = {"id": 1, "name": "test_lib"}
    server._docs_db.get_best_version.return_value = {"id": 1, "version": "1.0"}
    server._docs_db.clear_version_chunks = MagicMock()
    yield server._docs_db
    server._docs_db = None


@pytest.fixture(autouse=True)
def mock_backends():
    with (
        patch("wet_mcp.embedder.get_backend", new_callable=MagicMock) as mock_embed,
        patch("wet_mcp.reranker.get_reranker", new_callable=MagicMock) as mock_rerank,
    ):
        mock_backend = MagicMock()
        mock_backend.__class__.__name__ = "MockEmbedBackend"
        mock_embed.return_value = mock_backend

        mock_rerank_backend = MagicMock()
        mock_rerank_backend.__class__.__name__ = "MockRerankBackend"
        mock_rerank.return_value = mock_rerank_backend

        yield (mock_embed, mock_rerank)


@pytest.mark.asyncio
async def test_config_status(mock_settings, mock_docs_db, mock_backends):
    """Test config status action returns formatted JSON with server state."""
    res = await server.config("status")
    data = json.loads(res)

    assert "database" in data
    assert data["database"]["docs_indexed"]["total_chunks"] == 100
    assert "embedding" in data
    assert data["embedding"]["available"] is True
    assert "reranker" in data
    assert data["reranker"]["available"] is True
    assert "settings" in data
    assert data["settings"]["log_level"] == "DEBUG"
    assert data["settings"]["tool_timeout"] == 10


@pytest.mark.asyncio
async def test_config_set_valid_keys(mock_settings):
    """Test config set action updates valid keys."""
    # Test setting integer
    res = await server.config("set", "tool_timeout", "20")
    data = json.loads(res)
    assert data["status"] == "updated"
    assert data["key"] == "tool_timeout"
    assert data["value"] == 20
    assert mock_settings.tool_timeout == 20

    # Test setting string
    with patch("wet_mcp.server.logger") as mock_logger:
        res = await server.config("set", "log_level", "info")
        data = json.loads(res)
        assert data["status"] == "updated"
        assert data["value"] == "INFO"
        assert mock_settings.log_level == "INFO"
        mock_logger.remove.assert_called_once()
        mock_logger.add.assert_called_once()

    # Test setting arbitrary string (sync_folder is not specially handled but is valid)
    mock_settings.sync_folder = ""
    res = await server.config("set", "sync_folder", "/my/folder")
    data = json.loads(res)
    assert data["status"] == "updated"
    assert mock_settings.sync_folder == "/my/folder"


@pytest.mark.asyncio
async def test_config_set_boolean(mock_settings):
    """Test config set action handles boolean conversions."""
    # True conversions
    for val in ["true", "1", "yes", "TRUE", "Yes"]:
        res = await server.config("set", "wet_cache", val)
        data = json.loads(res)
        assert data["status"] == "updated"
        assert data["value"] is True
        assert mock_settings.wet_cache is True

    # False conversions (anything else)
    for val in ["false", "0", "no", "FALSE"]:
        res = await server.config("set", "wet_cache", val)
        data = json.loads(res)
        assert data["status"] == "updated"
        assert data["value"] is False
        assert mock_settings.wet_cache is False


@pytest.mark.asyncio
async def test_config_set_invalid_key(mock_settings):
    """Test config set action with an invalid key."""
    res = await server.config("set", "invalid_setting", "123")
    data = json.loads(res)
    assert "error" in data
    assert "Invalid key" in data["error"]
    assert "valid_keys" in data


@pytest.mark.asyncio
async def test_config_set_missing_args(mock_settings):
    """Test config set action missing key or value."""
    res = await server.config("set", "log_level")
    data = json.loads(res)
    assert "error" in data
    assert "key and value are required" in data["error"]

    res = await server.config("set")
    data = json.loads(res)
    assert "error" in data
    assert "key and value are required" in data["error"]


@pytest.mark.asyncio
async def test_config_cache_clear(mock_web_cache):
    """Test config cache_clear action."""
    res = await server.config("cache_clear")
    data = json.loads(res)
    assert data["status"] == "cache cleared"
    mock_web_cache.clear.assert_called_once()


@pytest.mark.asyncio
async def test_config_cache_clear_disabled():
    """Test config cache_clear action when cache is disabled."""
    # Override the mock_web_cache fixture to be None
    server._web_cache = None
    res = await server.config("cache_clear")
    data = json.loads(res)
    assert "error" in data
    assert data["error"] == "Cache is not enabled"


@pytest.mark.asyncio
async def test_config_docs_reindex_success(mock_docs_db):
    """Test config docs_reindex clears chunks for existing library."""
    res = await server.config("docs_reindex", "react")
    data = json.loads(res)

    assert data["status"] == "cleared"
    assert data["library"] == "react"
    mock_docs_db.get_library.assert_called_once_with("react")
    mock_docs_db.clear_version_chunks.assert_called_once_with(1)


@pytest.mark.asyncio
async def test_config_docs_reindex_missing_key():
    """Test config docs_reindex missing library key."""
    res = await server.config("docs_reindex")
    data = json.loads(res)
    assert "error" in data
    assert "key (library name) is required" in data["error"]


@pytest.mark.asyncio
async def test_config_docs_reindex_not_found(mock_docs_db):
    """Test config docs_reindex when library is not found."""
    mock_docs_db.get_library.return_value = None
    res = await server.config("docs_reindex", "unknown_lib")
    data = json.loads(res)

    assert "error" in data
    assert "not found in index" in data["error"]


@pytest.mark.asyncio
async def test_config_docs_reindex_db_not_initialized():
    """Test config docs_reindex when database is not initialized."""
    server._docs_db = None
    res = await server.config("docs_reindex", "react")
    data = json.loads(res)

    assert "error" in data
    assert data["error"] == "Docs database not initialized"


@pytest.mark.asyncio
async def test_config_unknown_action():
    """Test config with unknown action."""
    res = await server.config("unknown_action")
    data = json.loads(res)

    assert "error" in data
    assert "Unknown action: unknown_action" in data["error"]
    assert "valid_actions" in data
