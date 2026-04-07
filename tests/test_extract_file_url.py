import json
import pytest
from pathlib import Path
from wet_mcp.sources.crawler import extract

@pytest.mark.asyncio
async def test_extract_file_url_txt(tmp_path):
    f = tmp_path / "test.txt"
    f.write_text("Hello from file URL!")

    # On Unix, file:///path/to/file
    # urlparse('file:///tmp/test.txt').path is '/tmp/test.txt'
    url = f"file://{f.absolute()}"

    result_json = await extract([url])
    results = json.loads(result_json)

    assert len(results) == 1
    assert results[0]["url"] == url
    assert "Hello from file URL!" in results[0]["content"]
    assert results[0]["title"] == "test.txt"

@pytest.mark.asyncio
async def test_extract_file_url_unsafe(tmp_path):
    # Test a path that should be rejected (outside allowed dirs)
    # By default allowed dirs are HOME and /tmp
    # Let's try to access something like /etc/passwd if it exists,
    # but that might depend on environment.
    # Better to mock settings or use a path we know is outside.

    url = "file:///etc/passwd"
    result_json = await extract([url])
    results = json.loads(result_json)

    assert len(results) == 1
    assert results[0]["url"] == url
    assert "error" in results[0]
    assert "Path rejected" in results[0]["error"]

@pytest.mark.asyncio
async def test_extract_mixed_urls(tmp_path, mock_crawler_instance):
    from unittest.mock import AsyncMock, patch, MagicMock

    f = tmp_path / "local.txt"
    f.write_text("Local content")
    file_url = f"file://{f.absolute()}"
    web_url = "https://example.com"

    mock_result = MagicMock()
    mock_result.success = True
    mock_result.markdown = "Web content"
    mock_result.metadata = {"title": "Web Page"}
    mock_result.links = {"internal": [], "external": []}

    mock_crawler_instance.arun = AsyncMock(return_value=mock_result)

    with patch("wet_mcp.sources.crawler._get_crawler", return_value=mock_crawler_instance):
        result_json = await extract([file_url, web_url])
        results = json.loads(result_json)

        assert len(results) == 2

        # Order might not be guaranteed by gather, but they should both be there
        file_res = next(r for r in results if r["url"] == file_url)
        web_res = next(r for r in results if r["url"] == web_url)

        assert "Local content" in file_res["content"]
        assert "Web content" in web_res["content"]
