"""Tests for src/wet_mcp/server.py config tool."""

import json
import sys
from unittest.mock import patch

import pytest

# Mock mcp.tool decorator before importing server
with patch("mcp.server.fastmcp.FastMCP.tool") as mock_tool:
    mock_tool.return_value = lambda f: f
    from wet_mcp.server import config


@pytest.fixture
def mock_settings():
    with patch("wet_mcp.server.settings") as mock:
        mock.log_level = "INFO"
        mock.tool_timeout = 30
        mock.wet_cache = True
        mock.sync_enabled = False
        mock.sync_remote = ""
        mock.sync_folder = ""
        mock.sync_interval = 0
        mock.get_db_path.return_value = "/mock/db/path"
        mock.get_cache_db_path.return_value = "/mock/cache/path"
        yield mock


@pytest.fixture
def mock_logger():
    with patch("wet_mcp.server.logger") as mock:
        yield mock


@pytest.fixture
def mock_backends():
    with (
        patch("wet_mcp.server._embedding_dims", 768),
        patch("wet_mcp.embedder.get_backend") as mock_emb,
        patch("wet_mcp.reranker.get_reranker") as mock_rerank,
    ):

        class MockBackend:
            pass

        mock_emb.return_value = MockBackend()
        mock_rerank.return_value = MockBackend()
        yield mock_emb, mock_rerank


@pytest.fixture
def mock_docs_db():
    with patch("wet_mcp.server._docs_db") as mock:
        mock.stats.return_value = {"chunks": 100}
        yield mock


@pytest.fixture
def mock_web_cache():
    with patch("wet_mcp.server._web_cache") as mock:
        yield mock


@pytest.mark.asyncio
async def test_config_status(mock_settings, mock_backends, mock_docs_db):
    """Test status action returns correctly formatted config."""
    result = await config(action="status")
    data = json.loads(result)

    assert data["database"]["path"] == "/mock/db/path"
    assert data["database"]["docs_indexed"] == {"chunks": 100}
    assert data["embedding"]["backend"] == "MockBackend"
    assert data["embedding"]["dims"] == 768
    assert data["embedding"]["available"] is True
    assert data["reranker"]["backend"] == "MockBackend"
    assert data["reranker"]["available"] is True
    assert data["cache"]["enabled"] is True
    assert data["cache"]["path"] == "/mock/cache/path"
    assert data["sync"]["enabled"] is False
    assert data["settings"]["log_level"] == "INFO"
    assert data["settings"]["tool_timeout"] == 30


@pytest.mark.asyncio
async def test_config_set_requires_key_value(mock_settings):
    """Test set action requires key and value."""
    result = await config(action="set", key="log_level")
    data = json.loads(result)
    assert "error" in data
    assert "required" in data["error"].lower()

    result = await config(action="set", value="DEBUG")
    data = json.loads(result)
    assert "error" in data
    assert "required" in data["error"].lower()


@pytest.mark.asyncio
async def test_config_set_invalid_key(mock_settings):
    """Test set action validates key."""
    result = await config(action="set", key="invalid_key", value="value")
    data = json.loads(result)
    assert "error" in data
    assert "Invalid key" in data["error"]
    assert "valid_keys" in data


@pytest.mark.asyncio
async def test_config_set_log_level(mock_settings, mock_logger):
    """Test set action updates log_level and configures logger."""
    result = await config(action="set", key="log_level", value="debug")
    data = json.loads(result)

    assert data["status"] == "updated"
    assert data["key"] == "log_level"
    assert mock_settings.log_level == "DEBUG"
    mock_logger.remove.assert_called_once()
    mock_logger.add.assert_called_once_with(sys.stderr, level="DEBUG")


@pytest.mark.asyncio
async def test_config_set_tool_timeout(mock_settings):
    """Test set action updates tool_timeout."""
    result = await config(action="set", key="tool_timeout", value="60")
    data = json.loads(result)

    assert data["status"] == "updated"
    assert mock_settings.tool_timeout == 60


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "value,expected",
    [
        ("true", True),
        ("1", True),
        ("yes", True),
        ("false", False),
        ("0", False),
        ("no", False),
    ],
)
async def test_config_set_booleans(mock_settings, value, expected):
    """Test set action updates boolean flags correctly."""
    await config(action="set", key="wet_cache", value=value)
    assert mock_settings.wet_cache is expected

    mock_settings.configure_mock(sync_enabled=not expected)
    await config(action="set", key="sync_enabled", value=value)
    assert mock_settings.sync_enabled is expected


@pytest.mark.asyncio
async def test_config_set_other_keys(mock_settings):
    """Test set action updates generic keys."""
    result = await config(action="set", key="sync_remote", value="origin")
    data = json.loads(result)

    assert data["status"] == "updated"
    assert mock_settings.sync_remote == "origin"

    result = await config(action="set", key="sync_interval", value="3600")
    data = json.loads(result)
    assert data["status"] == "updated"
    assert mock_settings.sync_interval == 3600


@pytest.mark.asyncio
async def test_config_cache_clear(mock_web_cache):
    """Test cache_clear action."""
    result = await config(action="cache_clear")
    data = json.loads(result)

    assert data["status"] == "cache cleared"
    mock_web_cache.clear.assert_called_once()


@pytest.mark.asyncio
async def test_config_cache_clear_disabled():
    """Test cache_clear action when cache is disabled."""
    with patch("wet_mcp.server._web_cache", None):
        result = await config(action="cache_clear")
        data = json.loads(result)
        assert "error" in data
        assert "not enabled" in data["error"].lower()


@pytest.mark.asyncio
async def test_config_docs_reindex_missing_key():
    """Test docs_reindex requires a key."""
    result = await config(action="docs_reindex")
    data = json.loads(result)
    assert "error" in data
    assert "required" in data["error"].lower()


@pytest.mark.asyncio
async def test_config_docs_reindex_no_db():
    """Test docs_reindex when db is not initialized."""
    with patch("wet_mcp.server._docs_db", None):
        result = await config(action="docs_reindex", key="react")
        data = json.loads(result)
        assert "error" in data
        assert "not initialized" in data["error"].lower()


@pytest.mark.asyncio
async def test_config_docs_reindex_lib_not_found(mock_docs_db):
    """Test docs_reindex when library is not in index."""
    mock_docs_db.get_library.return_value = None
    result = await config(action="docs_reindex", key="unknown_lib")
    data = json.loads(result)

    assert "error" in data
    assert "not found" in data["error"].lower()
    mock_docs_db.get_library.assert_called_once_with("unknown_lib")


@pytest.mark.asyncio
async def test_config_docs_reindex_success(mock_docs_db):
    """Test docs_reindex successfully clears version chunks."""
    mock_docs_db.get_library.return_value = {"id": 1}
    mock_docs_db.get_best_version.return_value = {"id": 100}

    result = await config(action="docs_reindex", key="react")
    data = json.loads(result)

    assert data["status"] == "cleared"
    assert data["library"] == "react"
    mock_docs_db.get_best_version.assert_called_once_with(1)
    mock_docs_db.clear_version_chunks.assert_called_once_with(100)


@pytest.mark.asyncio
async def test_config_docs_reindex_no_best_version(mock_docs_db):
    """Test docs_reindex when library exists but no best version is found."""
    mock_docs_db.get_library.return_value = {"id": 1}
    mock_docs_db.get_best_version.return_value = None

    result = await config(action="docs_reindex", key="react")
    data = json.loads(result)

    assert data["status"] == "cleared"
    mock_docs_db.clear_version_chunks.assert_not_called()


@pytest.mark.asyncio
async def test_config_unknown_action():
    """Test handling of unknown actions."""
    result = await config(action="unknown_action")
    data = json.loads(result)
    assert "error" in data
    assert "Unknown action" in data["error"]
    assert "valid_actions" in data
