import json

import pytest

from wet_mcp.sources.crawler import extract


@pytest.mark.asyncio
async def test_extract_file_url_txt(tmp_path):
    f = tmp_path / "test.txt"
    f.write_text("Hello, file:// world!")

    file_url = f.as_uri()

    result_raw = await extract(urls=[file_url])
    result = json.loads(result_raw)

    assert len(result) == 1
    assert "Hello" in result[0]["content"]
    assert result[0]["url"] == file_url
    assert result[0].get("converter") == "markitdown"


@pytest.mark.asyncio
async def test_extract_file_url_unsafe():
    # Attempting to read a file that should be blocked
    file_url = "file:///etc/passwd"

    result_raw = await extract(urls=[file_url])
    result = json.loads(result_raw)

    assert len(result) == 1
    # Check if "Security Alert" or "rejected" is in the error message
    error = result[0].get("error", "")
    assert "Security Alert" in error or "rejected" in error
