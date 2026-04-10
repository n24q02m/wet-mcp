import asyncio
import json
import os
import sys
import importlib.util
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock
import pytest

# This test uses isolated loading because of the complex dependency environment
@pytest.mark.asyncio
async def test_extract_file_url_and_convert_concurrent(tmp_path):
    # Setup Mocks
    with MagicMock() as mock_loguru, \
         MagicMock() as mock_httpx, \
         MagicMock() as mock_crawl4ai, \
         MagicMock() as mock_aiolimiter, \
         MagicMock() as mock_markitdown:

        sys.modules["loguru"] = mock_loguru
        sys.modules["httpx"] = mock_httpx
        sys.modules["crawl4ai"] = mock_crawl4ai
        sys.modules["aiolimiter"] = mock_aiolimiter
        sys.modules["markitdown"] = mock_markitdown

        mock_config = MagicMock()
        mock_security = MagicMock()
        sys.modules["wet_mcp"] = MagicMock()
        sys.modules["wet_mcp.config"] = mock_config
        sys.modules["wet_mcp.security"] = mock_security

        class MockSettings:
            convert_allowed_dirs = ""
            convert_max_file_size = 100 * 1024 * 1024
            crawler_timeout = 60

        mock_config.settings = MockSettings()

        mock_mid = MagicMock()
        mock_mid.convert.return_value.text_content = "Converted Content"
        mock_markitdown.MarkItDown.return_value = mock_mid

        # Load module
        spec = importlib.util.spec_from_file_location("wet_mcp.sources.crawler", "src/wet_mcp/sources/crawler.py")
        crawler = importlib.util.module_from_spec(spec)
        sys.modules["wet_mcp.sources.crawler"] = crawler
        spec.loader.exec_module(crawler)

        # Test file:// URL
        test_file = tmp_path / "test.txt"
        test_file.write_text("Hello")
        file_url = f"file://{test_file.absolute()}"

        mock_security.is_safe_local_path.side_effect = lambda p, **kwargs: Path(p)

        result_json = await crawler.extract([file_url])
        results = json.loads(result_json)
        assert len(results) == 1
        assert results[0]["url"] == file_url
        assert results[0]["content"] == "Converted Content"

        # Test concurrent convert
        test_file2 = tmp_path / "test2.txt"
        test_file2.write_text("Hello 2")

        result_json = await crawler.convert_local_files([str(test_file), str(test_file2)])
        results = json.loads(result_json)
        assert len(results) == 2
        assert results[0]["content"] == "Converted Content"
        assert results[1]["content"] == "Converted Content"
