import sqlite3
import unittest
from unittest.mock import MagicMock, patch
from loguru import logger
from pathlib import Path
import sys
import os

# Add src to sys.path to import the real classes
sys.path.insert(0, os.path.abspath("src"))

from wet_mcp.db import DocsDB
from wet_mcp.cache import WebCache

class TestCleanup(unittest.TestCase):
    def test_docs_db_close_error(self):
        # We need to provide a path that doesn't trigger full initialization if possible
        # or just mock the connection after __init__
        with patch('sqlite3.connect'):
            db = DocsDB(Path("test.db"))
            mock_conn = MagicMock()
            mock_conn.close.side_effect = sqlite3.Error("close error")
            db._conn = mock_conn

            with patch.object(logger, "debug") as mock_logger:
                db.close()
                mock_logger.assert_called_once_with("Error closing database: close error")

    def test_web_cache_close_error(self):
        with patch('sqlite3.connect'):
            cache = WebCache(Path("cache.db"))
            mock_conn = MagicMock()
            mock_conn.close.side_effect = sqlite3.Error("cache close error")
            cache._conn = mock_conn

            with patch.object(logger, "debug") as mock_logger:
                cache.close()
                mock_logger.assert_called_once_with("Error closing cache database: cache close error")

if __name__ == "__main__":
    unittest.main()
