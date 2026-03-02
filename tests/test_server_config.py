import json
from unittest.mock import MagicMock, patch

import pytest

import wet_mcp.server as server_module

# Since the previous mock approach for mcp isn't fully robust,
# let's try to import config from server.py normally
# since the tests run in uv run pytest where mcp is installed
from wet_mcp.server import config, settings


@pytest.fixture(autouse=True)
def setup_teardown():
    # Save original settings
    original_log_level = settings.log_level
    original_tool_timeout = settings.tool_timeout
    original_wet_cache = settings.wet_cache
    original_sync_enabled = settings.sync_enabled
    original_sync_interval = settings.sync_interval
    original_sync_remote = settings.sync_remote
    yield
    # Restore original settings
    settings.log_level = original_log_level
    settings.tool_timeout = original_tool_timeout
    settings.wet_cache = original_wet_cache
    settings.sync_enabled = original_sync_enabled
    settings.sync_interval = original_sync_interval
    settings.sync_remote = original_sync_remote


@pytest.mark.asyncio
async def test_config_status():
    with (
        patch("wet_mcp.embedder.get_backend") as mock_get_backend,
        patch("wet_mcp.reranker.get_reranker") as mock_get_reranker,
        patch("wet_mcp.server._docs_db") as mock_docs_db,
    ):
        mock_get_backend.return_value = MagicMock()
        mock_get_reranker.return_value = MagicMock()
        mock_docs_db.stats.return_value = {"chunks": 100}

        result_str = await config(action="status")
        result = json.loads(result_str)

        assert "database" in result
        assert "embedding" in result
        assert "reranker" in result
        assert "cache" in result
        assert "sync" in result
        assert "settings" in result


@pytest.mark.asyncio
async def test_config_set_missing_args():
    result_str = await config(action="set")
    result = json.loads(result_str)
    assert "error" in result
    assert "key and value are required" in result["error"]


@pytest.mark.asyncio
async def test_config_set_invalid_key():
    result_str = await config(action="set", key="invalid_key", value="123")
    result = json.loads(result_str)
    assert "error" in result
    assert "Invalid key" in result["error"]


@pytest.mark.asyncio
async def test_config_set_log_level():
    with patch("wet_mcp.server.logger") as mock_logger:
        result_str = await config(action="set", key="log_level", value="DEBUG")
        result = json.loads(result_str)
        assert result["status"] == "updated"
        assert result["key"] == "log_level"
        assert result["value"] == "DEBUG"
        assert settings.log_level == "DEBUG"
        mock_logger.remove.assert_called_once()
        mock_logger.add.assert_called_once()


@pytest.mark.asyncio
async def test_config_set_tool_timeout():
    result_str = await config(action="set", key="tool_timeout", value="100")
    result = json.loads(result_str)
    assert result["status"] == "updated"
    assert result["key"] == "tool_timeout"
    assert result["value"] == 100
    assert settings.tool_timeout == 100


@pytest.mark.asyncio
async def test_config_set_wet_cache():
    result_str = await config(action="set", key="wet_cache", value="true")
    result = json.loads(result_str)
    assert result["status"] == "updated"
    assert result["key"] == "wet_cache"
    assert result["value"] is True
    assert settings.wet_cache is True


@pytest.mark.asyncio
async def test_config_set_sync_enabled():
    result_str = await config(action="set", key="sync_enabled", value="false")
    result = json.loads(result_str)
    assert result["status"] == "updated"
    assert result["key"] == "sync_enabled"
    assert result["value"] is False
    assert settings.sync_enabled is False


@pytest.mark.asyncio
async def test_config_set_sync_interval():
    result_str = await config(action="set", key="sync_interval", value="3600")
    result = json.loads(result_str)
    assert result["status"] == "updated"
    assert result["key"] == "sync_interval"
    assert result["value"] == 3600
    assert settings.sync_interval == 3600


@pytest.mark.asyncio
async def test_config_set_other_valid_key():
    result_str = await config(action="set", key="sync_remote", value="some_remote")
    result = json.loads(result_str)
    assert result["status"] == "updated"
    assert result["key"] == "sync_remote"
    assert result["value"] == "some_remote"
    assert settings.sync_remote == "some_remote"


@pytest.mark.asyncio
async def test_config_cache_clear_enabled():
    with patch("wet_mcp.server._web_cache") as mock_cache:
        # We need _web_cache to be true
        server_module._web_cache = mock_cache
        mock_cache.__bool__.return_value = True

        result_str = await config(action="cache_clear")
        result = json.loads(result_str)
        assert result["status"] == "cache cleared"
        mock_cache.clear.assert_called_once()


@pytest.mark.asyncio
async def test_config_cache_clear_disabled():
    with patch("wet_mcp.server._web_cache", None):
        result_str = await config(action="cache_clear")
        result = json.loads(result_str)
        assert "error" in result
        assert "Cache is not enabled" in result["error"]


@pytest.mark.asyncio
async def test_config_docs_reindex_missing_key():
    result_str = await config(action="docs_reindex")
    result = json.loads(result_str)
    assert "error" in result
    assert "key (library name) is required" in result["error"]


@pytest.mark.asyncio
async def test_config_docs_reindex_no_db():
    with patch("wet_mcp.server._docs_db", None):
        result_str = await config(action="docs_reindex", key="react")
        result = json.loads(result_str)
        assert "error" in result
        assert "Docs database not initialized" in result["error"]


@pytest.mark.asyncio
async def test_config_docs_reindex_success():
    mock_db = MagicMock()
    mock_db.get_library.return_value = {"id": 1}
    mock_db.get_best_version.return_value = {"id": 2}

    with patch("wet_mcp.server._docs_db", mock_db):
        result_str = await config(action="docs_reindex", key="react")
        result = json.loads(result_str)
        assert result["status"] == "cleared"
        assert result["library"] == "react"
        mock_db.clear_version_chunks.assert_called_once_with(2)


@pytest.mark.asyncio
async def test_config_docs_reindex_lib_not_found():
    mock_db = MagicMock()
    mock_db.get_library.return_value = None

    with patch("wet_mcp.server._docs_db", mock_db):
        result_str = await config(action="docs_reindex", key="react")
        result = json.loads(result_str)
        assert "error" in result
        assert "not found in index" in result["error"]


@pytest.mark.asyncio
async def test_config_unknown_action():
    result_str = await config(action="unknown")
    result = json.loads(result_str)
    assert "error" in result
    assert "Unknown action" in result["error"]
