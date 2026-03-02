import json
import sys
from unittest.mock import patch

import pytest

# Memory context: To test @mcp.tool decorated functions in isolation without a real MCP server instance
# (e.g., in tests/test_server_config.py), the mcp.tool decorator must be mocked to return the
# original function, ensuring the tool remains an awaitable coroutine.

# We must mock dependencies BEFORE importing `wet_mcp.server` to prevent initialization side-effects.
with patch("wet_mcp.server.mcp.tool", lambda *args, **kwargs: lambda f: f):
    from wet_mcp.server import config


@pytest.fixture
def mock_settings():
    with patch("wet_mcp.server.settings") as mock:
        mock.get_db_path.return_value = "/mock/db/path"
        mock.get_cache_db_path.return_value = "/mock/cache/path"
        mock.wet_cache = True
        mock.sync_enabled = False
        mock.sync_remote = "mock_remote"
        mock.sync_folder = "mock_folder"
        mock.sync_interval = 3600
        mock.log_level = "INFO"
        mock.tool_timeout = 60
        yield mock


@pytest.fixture
def mock_docs_db():
    with patch("wet_mcp.server._docs_db") as mock:
        mock.stats.return_value = {"chunks": 100}
        yield mock


@pytest.fixture
def mock_web_cache():
    with patch("wet_mcp.server._web_cache") as mock:
        yield mock


@pytest.fixture
def mock_backends():
    with (
        patch("wet_mcp.embedder.get_backend") as mock_embed,
        patch("wet_mcp.reranker.get_reranker") as mock_rerank,
    ):
        mock_embed.return_value.__class__.__name__ = "MockEmbedder"
        mock_rerank.return_value.__class__.__name__ = "MockReranker"

        yield mock_embed, mock_rerank


@pytest.fixture
def mock_logger():
    with patch("wet_mcp.server.logger") as mock:
        yield mock


@pytest.mark.asyncio
async def test_config_status(mock_settings, mock_docs_db, mock_backends):
    """Test the status action returns expected configuration."""
    res = await config("status")
    data = json.loads(res)

    assert data["database"]["path"] == "/mock/db/path"
    assert data["database"]["docs_indexed"] == {"chunks": 100}
    assert data["embedding"]["available"] is True
    assert data["embedding"]["backend"] == "MockEmbedder"
    assert data["reranker"]["available"] is True
    assert data["reranker"]["backend"] == "MockReranker"
    assert data["cache"]["enabled"] is True
    assert data["cache"]["path"] == "/mock/cache/path"
    assert data["sync"]["enabled"] is False
    assert data["sync"]["remote"] == "mock_remote"
    assert data["settings"]["log_level"] == "INFO"
    assert data["settings"]["tool_timeout"] == 60


@pytest.mark.asyncio
async def test_config_set_missing_args():
    """Test set action with missing key or value."""
    res = await config("set")
    data = json.loads(res)
    assert "error" in data
    assert "required" in data["error"]

    res = await config("set", key="log_level")
    data = json.loads(res)
    assert "error" in data


@pytest.mark.asyncio
async def test_config_set_invalid_key():
    """Test set action with invalid key."""
    res = await config("set", key="invalid_key", value="val")
    data = json.loads(res)
    assert "error" in data
    assert "Invalid key" in data["error"]
    assert "valid_keys" in data


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "key,value,expected_type,expected_val",
    [
        ("tool_timeout", "120", int, 120),
        ("wet_cache", "true", bool, True),
        ("wet_cache", "0", bool, False),
        ("sync_enabled", "yes", bool, True),
        ("sync_interval", "300", int, 300),
        ("sync_remote", "new_remote", str, "new_remote"),
    ],
)
async def test_config_set_success(
    mock_settings, key, value, expected_type, expected_val
):
    """Test successful setting of valid configuration keys."""

    def mock_getattr(obj, attr, *args):
        if obj is mock_settings and attr == key:
            return expected_val
        if len(args) > 0:
            return getattr(obj, attr, args[0])
        return getattr(obj, attr)

    with patch("wet_mcp.server.getattr", side_effect=mock_getattr):
        res = await config("set", key=key, value=value)
        data = json.loads(res)

        assert data["status"] == "updated"
        assert data["key"] == key
        assert data["value"] == expected_val


@pytest.mark.asyncio
async def test_config_set_log_level(mock_settings, mock_logger):
    """Test setting log_level updates the logger."""
    res = await config("set", key="log_level", value="debug")
    data = json.loads(res)

    assert data["status"] == "updated"
    assert mock_settings.log_level == "DEBUG"
    mock_logger.remove.assert_called_once()
    mock_logger.add.assert_called_once_with(sys.stderr, level="DEBUG")


@pytest.mark.asyncio
async def test_config_cache_clear_success(mock_web_cache):
    """Test clearing cache when enabled."""
    res = await config("cache_clear")
    data = json.loads(res)

    assert data["status"] == "cache cleared"
    mock_web_cache.clear.assert_called_once()


@pytest.mark.asyncio
async def test_config_cache_clear_disabled():
    """Test clearing cache when disabled (None)."""
    with patch("wet_mcp.server._web_cache", None):
        res = await config("cache_clear")
        data = json.loads(res)

        assert "error" in data
        assert "Cache is not enabled" in data["error"]


@pytest.mark.asyncio
async def test_config_docs_reindex_missing_key():
    """Test docs_reindex with missing library key."""
    res = await config("docs_reindex")
    data = json.loads(res)

    assert "error" in data
    assert "required" in data["error"]


@pytest.mark.asyncio
async def test_config_docs_reindex_no_db():
    """Test docs_reindex when db is not initialized."""
    with patch("wet_mcp.server._docs_db", None):
        res = await config("docs_reindex", key="react")
        data = json.loads(res)

        assert "error" in data
        assert "not initialized" in data["error"]


@pytest.mark.asyncio
async def test_config_docs_reindex_not_found(mock_docs_db):
    """Test docs_reindex when library is not found."""
    mock_docs_db.get_library.return_value = None

    res = await config("docs_reindex", key="unknown_lib")
    data = json.loads(res)

    assert "error" in data
    assert "not found" in data["error"]


@pytest.mark.asyncio
async def test_config_docs_reindex_success(mock_docs_db):
    """Test successful docs_reindex."""
    mock_docs_db.get_library.return_value = {"id": 1, "name": "react"}
    mock_docs_db.get_best_version.return_value = {"id": 10, "version": "18.0.0"}

    res = await config("docs_reindex", key="react")
    data = json.loads(res)

    assert data["status"] == "cleared"
    assert data["library"] == "react"
    mock_docs_db.clear_version_chunks.assert_called_once_with(10)


@pytest.mark.asyncio
async def test_config_invalid_action():
    """Test unknown action returns error."""
    res = await config("unknown_action")
    data = json.loads(res)

    assert "error" in data
    assert "Unknown action" in data["error"]
    assert "valid_actions" in data
