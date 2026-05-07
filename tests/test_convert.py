"""Tests for local file conversion via convert_local_files."""

import json

import pytest

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
