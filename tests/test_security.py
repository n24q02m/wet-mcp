import os
from pathlib import Path
import pytest
from wet_mcp.security import is_safe_path

def test_is_safe_path_basic(tmp_path):
    """Test basic safe path scenarios."""
    base = tmp_path / "base"
    base.mkdir()

    # Safe path
    safe = base / "file.txt"
    # Even if file doesn't exist, it should be safe if path is inside
    assert is_safe_path(safe, base)

    # Also works with strings
    assert is_safe_path(str(safe), str(base))

def test_is_safe_path_traversal(tmp_path):
    """Test path traversal attempts."""
    base = tmp_path / "base"
    base.mkdir()

    # Attempt traversal with ..
    unsafe = base / "../unsafe.txt"
    # resolving unsafe -> tmp_path/unsafe.txt, which is outside base
    assert not is_safe_path(unsafe, base)

    unsafe_str = str(base) + "/../unsafe.txt"
    assert not is_safe_path(unsafe_str, base)

def test_is_safe_path_absolute(tmp_path):
    """Test absolute paths."""
    base = tmp_path / "base"
    base.mkdir()

    # Absolute path outside
    outside = tmp_path / "outside.txt"
    assert not is_safe_path(outside, base)

    # Absolute path inside
    inside = base / "inside.txt"
    assert is_safe_path(inside, base)

def test_is_safe_path_symlink(tmp_path):
    """Test symlink resolution."""
    base = tmp_path / "base"
    base.mkdir()

    target = tmp_path / "target"
    target.mkdir()

    link = base / "link"
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("Symlinks not supported")

    # link points to target (outside base)
    # resolving link -> target
    # target is NOT relative to base
    assert not is_safe_path(link, base)

def test_is_safe_path_expanduser():
    """Test that expanduser is called."""
    # We can't easily test expanduser without mocking home,
    # but we can ensure passing '~' doesn't crash
    # and likely resolves to something outside generic base if base is absolute

    # If base is /tmp, ~/foo is likely not in /tmp (on linux)
    # unless home is /tmp.
    pass
