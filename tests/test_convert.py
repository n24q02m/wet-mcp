"""Tests for local file conversion via convert_local_files."""

import json

import pytest
from unittest.mock import patch

from wet_mcp.sources.crawler import convert_local_files


async def test_convert_local_files_txt(tmp_path):
    f = tmp_path / "test.txt"
    f.write_text("Hello, world!")
    result = await convert_local_files([str(f)])
    data = json.loads(result)
    assert len(data) == 1
    assert "Hello" in data[0]["content"]
    assert data[0]["path"] == str(f)
    assert data[0]["title"] == "test.txt"


async def test_convert_local_files_nonexistent():
    result = await convert_local_files(["/nonexistent/file.pdf"])
    data = json.loads(result)
    assert len(data) == 1
    assert "error" in data[0]


async def test_convert_local_files_csv(tmp_path):
    f = tmp_path / "data.csv"
    f.write_text("name,age\nAlice,30\nBob,25")
    result = await convert_local_files([str(f)])
    data = json.loads(result)
    assert len(data) == 1
    assert "Alice" in data[0]["content"]


async def test_convert_local_files_max_files():
    paths = [f"/tmp/file{i}.txt" for i in range(11)]
    result = await convert_local_files(paths)
    assert "Error" in result
    assert "Maximum" in result


async def test_convert_local_files_multiple(tmp_path):
    f1 = tmp_path / "a.txt"
    f1.write_text("First file")
    f2 = tmp_path / "b.txt"
    f2.write_text("Second file")
    result = await convert_local_files([str(f1), str(f2)])
    data = json.loads(result)
    assert len(data) == 2
    assert all("content" in d for d in data)


@pytest.mark.asyncio
async def test_extract_file_url(tmp_path):
    from wet_mcp.sources.crawler import extract

    f = tmp_path / "test_extract.txt"
    f.write_text("Extracted from file URL")
    file_url = f"file://{f}"

    result = await extract([file_url])
    data = json.loads(result)

    assert len(data) == 1
    assert data[0]["url"] == file_url
    assert "Extracted from file URL" in data[0]["content"]
    assert data[0]["title"] == "test_extract.txt"


@pytest.mark.asyncio
async def test_extract_file_url_unsafe():
    from wet_mcp.sources.crawler import extract

    file_url = "file:///etc/passwd"

    result = await extract([file_url])
    data = json.loads(result)

    assert len(data) == 1
    assert "error" in data[0]
    assert "Path rejected or unsafe" in data[0]["error"]

@pytest.mark.asyncio
async def test_get_allowed_dirs_from_settings(monkeypatch):
    from wet_mcp.config import settings
    from wet_mcp.sources.crawler import _get_allowed_dirs

    monkeypatch.setattr(settings, "convert_allowed_dirs", "/tmp/a, /tmp/b")
    allowed = _get_allowed_dirs()
    assert len(allowed) == 2
    assert str(allowed[0]) == "/tmp/a"
    assert str(allowed[1]) == "/tmp/b"

@pytest.mark.asyncio
async def test_extract_file_url_invalid():
    from wet_mcp.sources.crawler import _extract_local_file
    result = await _extract_local_file("http://not-a-file-url")
    assert "Invalid file URL" in result["error"]

async def test_extract_file_url_windows_path(monkeypatch, tmp_path):
    import os
    from wet_mcp.sources.crawler import _extract_local_file

    f = tmp_path / "win.txt"
    f.write_text("Windows path test")

    # Mock os.name to "nt" and simulate a Windows-style file URL
    monkeypatch.setattr(os, "name", "nt")
    # On Windows, file:///C:/path becomes /C:/path after unquote(url[7:])
    # We want to test that the leading slash is stripped.
    # So we'll use a URL that results in /C:/path
    fake_url = "file:///C:/fake/path.txt"

    # We don't actually want to call is_safe_local_path with this fake path as it won't exist
    # But we want to test the path normalization logic.
    # Actually, let's just test that it reaches is_safe_local_path with the right string.

    with patch("wet_mcp.sources.crawler.is_safe_local_path") as mock_safe:
        mock_safe.return_value = None
        await _extract_local_file("file:///C:/fake/path.txt")
        # url[7:] is /C:/fake/path.txt
        # after unquote it's same
        # it starts with / and has : at index 2
        # it should become C:/fake/path.txt
        mock_safe.assert_called()
        args, kwargs = mock_safe.call_args
        assert args[0] == "C:/fake/path.txt"

@pytest.mark.asyncio
async def test_extract_file_url_exception():
    from wet_mcp.sources.crawler import _extract_local_file
    with patch("wet_mcp.sources.crawler._get_allowed_dirs", side_effect=Exception("Unexpected error")):
        result = await _extract_local_file("file:///some/path")
        assert "Unexpected error" in result["error"]
