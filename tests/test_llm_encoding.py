import base64
import os

from wet_mcp.llm import encode_image


def create_dummy_file(tmp_path, content: bytes) -> str:
    p = tmp_path / "test_file"
    p.write_bytes(content)
    return str(p)


def standard_encode(path: str) -> str:
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


def test_encode_empty_file(tmp_path):
    path = create_dummy_file(tmp_path, b"")
    assert encode_image(path) == standard_encode(path)


def test_encode_small_file(tmp_path):
    path = create_dummy_file(tmp_path, b"hello world")
    assert encode_image(path) == standard_encode(path)


def test_encode_large_file(tmp_path):
    # 5MB file
    content = os.urandom(5 * 1024 * 1024)
    path = create_dummy_file(tmp_path, content)
    assert encode_image(path) == standard_encode(path)


def test_encode_file_not_multiple_of_3(tmp_path):
    # 1024 bytes (1024 % 3 = 1)
    content = os.urandom(1024)
    path = create_dummy_file(tmp_path, content)
    assert encode_image(path) == standard_encode(path)

    # 1025 bytes (1025 % 3 = 2)
    content = os.urandom(1025)
    path = create_dummy_file(tmp_path, content)
    assert encode_image(path) == standard_encode(path)


def test_encode_exact_chunk_boundary(tmp_path):
    # 192KB * 2
    chunk_size = 196608
    content = os.urandom(chunk_size * 2)
    path = create_dummy_file(tmp_path, content)
    assert encode_image(path) == standard_encode(path)


def test_encode_chunk_boundary_plus_one(tmp_path):
    # 192KB + 1 byte
    chunk_size = 196608
    content = os.urandom(chunk_size + 1)
    path = create_dummy_file(tmp_path, content)
    assert encode_image(path) == standard_encode(path)


def test_encode_with_mime_type(tmp_path):
    path = create_dummy_file(tmp_path, b"hello")
    # standard: aGVsbG8=
    expected = "data:image/jpeg;base64,aGVsbG8="
    assert encode_image(path, mime_type="image/jpeg") == expected
