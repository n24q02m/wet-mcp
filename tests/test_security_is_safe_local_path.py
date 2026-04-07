from pathlib import Path
from unittest.mock import patch

import pytest

from wet_mcp.security import is_safe_local_path


def test_safe_local_path_valid_file(tmp_path):
    """Test a valid file path returns the resolved Path."""
    f = tmp_path / "test.txt"
    f.write_text("hello world")
    result = is_safe_local_path(str(f))
    assert result == f.resolve()
    assert isinstance(result, Path)


def test_safe_local_path_dotdot_traversal(tmp_path):
    """Paths containing '..' components are blocked before resolution."""
    f = tmp_path / "test.txt"
    f.write_text("hello")
    # Use a string that contains '..'
    evil_path = str(tmp_path / "subdir" / ".." / "test.txt")
    # Even if it resolves to a valid file, the '..' in parts should trigger the block
    assert is_safe_local_path(evil_path) is None


def test_safe_local_path_resolve_failure():
    """Returns None if Path.resolve() raises OSError or ValueError."""
    with patch.object(Path, "resolve", side_effect=OSError("Resolution failed")):
        assert is_safe_local_path("/some/path") is None

    with patch.object(Path, "resolve", side_effect=ValueError("Invalid path")):
        assert is_safe_local_path("/some/path") is None


def test_safe_local_path_not_a_file(tmp_path):
    """Returns None if the path is a directory instead of a file."""
    d = tmp_path / "subdir"
    d.mkdir()
    assert is_safe_local_path(str(d)) is None


def test_safe_local_path_allowed_dirs(tmp_path):
    """Tests allowed_dirs validation."""
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    forbidden = tmp_path / "forbidden"
    forbidden.mkdir()

    f1 = allowed / "ok.txt"
    f1.write_text("ok")
    f2 = forbidden / "no.txt"
    f2.write_text("no")

    # Path inside allowed dir
    assert is_safe_local_path(str(f1), allowed_dirs=[allowed]) == f1.resolve()

    # Path outside allowed dir
    assert is_safe_local_path(str(f2), allowed_dirs=[allowed]) is None


def test_safe_local_path_symlink_escape(tmp_path):
    """Symlinks escaping allowed_dirs are caught after resolution."""
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("secret")

    link = allowed / "link.txt"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("Symlinks not supported on this platform")

    # Resolution (strict=True) will follow the link to outside.txt
    # is_relative_to(allowed) will then fail.
    assert is_safe_local_path(str(link), allowed_dirs=[allowed]) is None


def test_safe_local_path_oversized_file(tmp_path):
    """Returns None when file exceeds max_size."""
    f = tmp_path / "big.txt"
    f.write_text("this is a bit long")
    size = f.stat().st_size

    # Exactly at limit
    assert is_safe_local_path(str(f), max_size=size) == f.resolve()

    # Just under limit
    assert is_safe_local_path(str(f), max_size=size - 1) is None


def test_safe_local_path_stat_failure(tmp_path):
    """Returns None if Path.stat() raises OSError."""
    f = tmp_path / "test.txt"
    f.write_text("hello")

    # We need to mock stat on the resolved path object
    resolved_path = f.resolve()

    # Patch Path.is_file to return True for our fake path
    # and Path.resolve to return our fake path
    with patch.object(Path, "resolve", return_value=resolved_path):
        with patch.object(Path, "is_file", return_value=True):
            with patch.object(Path, "stat", side_effect=OSError("Stat failed")):
                assert is_safe_local_path(str(f)) is None


def test_safe_local_path_nonexistent():
    """Strict resolution of nonexistent files returns None."""
    # Since strict=True is used in resolve(), nonexistent files raise OSError
    assert is_safe_local_path("/tmp/definitely_not_a_real_file_12345") is None
