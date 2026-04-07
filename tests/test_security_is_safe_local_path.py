import importlib.util
import sys
from unittest.mock import MagicMock, patch

import pytest


# Manually load the module to avoid side-effect imports in wet_mcp.__init__ or server.py
def load_security():
    # Mock dependencies before any imports
    sys.modules["web_core"] = MagicMock()
    sys.modules["web_core.http"] = MagicMock()
    sys.modules["web_core.http.client"] = MagicMock()
    sys.modules["loguru"] = MagicMock()

    spec = importlib.util.spec_from_file_location(
        "wet_mcp.security", "src/wet_mcp/security.py"
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["wet_mcp.security"] = mod
    spec.loader.exec_module(mod)
    return mod


security = load_security()
is_safe_local_path = security.is_safe_local_path
wrap_external_content = security.wrap_external_content


def test_safe_local_path_valid_file(tmp_path):
    f = tmp_path / "test.txt"
    f.write_text("hello")
    result = is_safe_local_path(str(f))
    assert result == f.resolve()


def test_safe_local_path_rejects_dotdot(tmp_path):
    evil_path = str(tmp_path / "subdir" / ".." / "test.txt")
    assert is_safe_local_path(evil_path) is None


def test_safe_local_path_resolve_failure():
    # Patch Path.resolve in the module's namespace
    with patch.object(security.Path, "resolve", side_effect=OSError("Access denied")):
        assert is_safe_local_path("/some/path") is None

    with patch.object(security.Path, "resolve", side_effect=ValueError("Invalid path")):
        assert is_safe_local_path("/some/path") is None


def test_safe_local_path_not_a_file(tmp_path):
    assert is_safe_local_path(str(tmp_path)) is None


def test_safe_local_path_allowed_dirs(tmp_path):
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    f = allowed / "test.txt"
    f.write_text("hello")

    assert is_safe_local_path(str(f), allowed_dirs=[allowed]) == f.resolve()

    outside = tmp_path / "outside"
    outside.mkdir()
    f2 = outside / "test.txt"
    f2.write_text("hello")
    assert is_safe_local_path(str(f2), allowed_dirs=[allowed]) is None


def test_safe_local_path_oversized_file(tmp_path):
    f = tmp_path / "big.txt"
    f.write_text("too much data")
    assert is_safe_local_path(str(f), max_size=5) is None


def test_safe_local_path_stat_oserror(tmp_path):
    f = tmp_path / "test.txt"
    f.write_text("hello")

    with patch.object(security.Path, "is_file", return_value=True):
        with patch.object(security.Path, "stat", side_effect=OSError("Disk error")):
            assert is_safe_local_path(str(f)) is None


def test_safe_local_path_allowed_dirs_symlink_escape(tmp_path):
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    secret = tmp_path / "secret.txt"
    secret.write_text("sensitive")

    link = allowed / "link.txt"
    try:
        link.symlink_to(secret)
    except (OSError, NotImplementedError):
        pytest.skip("Symlinks not supported on this platform")

    assert is_safe_local_path(str(link), allowed_dirs=[allowed]) is None


def test_wrap_external_content_success():
    result = wrap_external_content("test_tool", "some content")
    assert "<untrusted_test_tool_content>" in result
    assert "some content" in result
    assert "[SECURITY:" in result


def test_wrap_external_content_error():
    result = wrap_external_content("test_tool", "Error: something went wrong")
    assert result == "Error: something went wrong"
