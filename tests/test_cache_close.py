import sqlite3
import pytest
from unittest.mock import MagicMock
from wet_mcp.cache import WebCache
from loguru import logger

def test_close_error_logged(tmp_path):
    cache_path = tmp_path / "test_close.db"
    cache = WebCache(cache_path)

    # Mock the connection to raise an error on close
    mock_conn = MagicMock()
    mock_conn.close.side_effect = sqlite3.Error("Mocked error")
    cache._conn = mock_conn

    # Use loguru's add method to capture logs
    logs = []
    handler_id = logger.add(lambda msg: logs.append(msg), level="WARNING")

    try:
        cache.close()
        # Check if the error message is in the captured logs
        assert any("Error closing cache database: Mocked error" in str(log) for log in logs)
    finally:
        logger.remove(handler_id)

def test_close_success(tmp_path):
    cache_path = tmp_path / "test_close_success.db"
    cache = WebCache(cache_path)
    cache.close() # Should not raise or log warning
