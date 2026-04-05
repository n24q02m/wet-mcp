from pathlib import Path
from unittest.mock import patch

import pytest


@pytest.fixture
def is_safe_local_path_fn():
    """Lazy import to avoid pydantic.root_model KeyError at collection time."""
    from wet_mcp.security import is_safe_local_path

    return is_safe_local_path


def test_is_safe_local_path_valid_file(tmp_path, is_safe_local_path_fn):
    f = tmp_path / "test.txt"
    f.write_text("content")
    result = is_safe_local_path_fn(str(f))
    assert result == f.resolve()
    assert isinstance(result, Path)


def test_is_safe_local_path_path_object_input(tmp_path, is_safe_local_path_fn):
    f = tmp_path / "test.txt"
    f.write_text("content")
    result = is_safe_local_path_fn(f)
    assert result == f.resolve()


def test_is_safe_local_path_nonexistent(tmp_path, is_safe_local_path_fn):
    f = tmp_path / "nonexistent.txt"
    assert is_safe_local_path_fn(str(f)) is None


def test_is_safe_local_path_directory(tmp_path, is_safe_local_path_fn):
    assert is_safe_local_path_fn(str(tmp_path)) is None


def test_is_safe_local_path_traversal_dotdot(tmp_path, is_safe_local_path_fn):
    f = tmp_path / "test.txt"
    f.write_text("content")
    # path_str with ..
    evil_path = str(tmp_path / "subdir" / ".." / "test.txt")
    # Path(evil_path).parts will contain '..' if it's not resolved yet
    assert is_safe_local_path_fn(evil_path) is None


def test_is_safe_local_path_dots_in_filename(tmp_path, is_safe_local_path_fn):
    f = tmp_path / "report..v2.txt"
    f.write_text("content")
    assert is_safe_local_path_fn(str(f)) == f.resolve()


def test_is_safe_local_path_oversized(tmp_path, is_safe_local_path_fn):
    f = tmp_path / "big.txt"
    f.write_text("x" * 100)
    assert is_safe_local_path_fn(str(f), max_size=50) is None


def test_is_safe_local_path_allowed_dirs(tmp_path, is_safe_local_path_fn):
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    f = allowed / "test.txt"
    f.write_text("hello")

    # Success case
    assert is_safe_local_path_fn(str(f), allowed_dirs=[allowed]) == f.resolve()

    # Outside case
    outside = tmp_path / "outside"
    outside.mkdir()
    f2 = outside / "test.txt"
    f2.write_text("hello")
    assert is_safe_local_path_fn(str(f2), allowed_dirs=[allowed]) is None


def test_is_safe_local_path_symlink_escape(tmp_path, is_safe_local_path_fn):
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    secret = tmp_path / "secret.txt"
    secret.write_text("sensitive")

    link = allowed / "link.txt"
    try:
        link.symlink_to(secret)
    except OSError:
        pytest.skip("Symlinks not supported on this platform/user")

    assert is_safe_local_path_fn(str(link), allowed_dirs=[allowed]) is None


def test_is_safe_local_path_resolve_oserror(is_safe_local_path_fn):
    with patch("pathlib.Path.resolve", side_effect=OSError("Permission denied")):
        assert is_safe_local_path_fn("/some/path") is None


def test_is_safe_local_path_resolve_valueerror(is_safe_local_path_fn):
    with patch("pathlib.Path.resolve", side_effect=ValueError("Invalid path")):
        assert is_safe_local_path_fn("/some/path") is None


def test_is_safe_local_path_stat_oserror(tmp_path, is_safe_local_path_fn):
    f = tmp_path / "test.txt"
    f.write_text("content")

    with patch("pathlib.Path.stat", side_effect=OSError("Stat failed")):
        assert is_safe_local_path_fn(str(f)) is None


def test_is_safe_local_path_complex_allowed_dirs(tmp_path, is_safe_local_path_fn):
    # Multiple allowed dirs
    d1 = tmp_path / "d1"
    d1.mkdir()
    d2 = tmp_path / "d2"
    d2.mkdir()

    f1 = d1 / "f1.txt"
    f1.write_text("1")
    f2 = d2 / "f2.txt"
    f2.write_text("2")

    allowed = [d1, d2]
    assert is_safe_local_path_fn(str(f1), allowed_dirs=allowed) == f1.resolve()
    assert is_safe_local_path_fn(str(f2), allowed_dirs=allowed) == f2.resolve()

    f3 = tmp_path / "f3.txt"
    f3.write_text("3")
    assert is_safe_local_path_fn(str(f3), allowed_dirs=allowed) is None
