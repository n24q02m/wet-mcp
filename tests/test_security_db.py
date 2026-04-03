import sys
from pathlib import Path
from unittest.mock import patch

import pytest

# Bootstrap wet_mcp.db (similar to test_db.py)
_src_root = Path(__file__).resolve().parent.parent / "src"
if "wet_mcp" not in sys.modules:
    import types

    _pkg = types.ModuleType("wet_mcp")
    _pkg.__path__ = [str(_src_root / "wet_mcp")]
    sys.modules["wet_mcp"] = _pkg

if "wet_mcp.sources" not in sys.modules:
    import types

    _sources_pkg = types.ModuleType("wet_mcp.sources")
    _sources_pkg.__path__ = [str(_src_root / "wet_mcp" / "sources")]
    sys.modules["wet_mcp.sources"] = _sources_pkg

if "wet_mcp.sources.docs" not in sys.modules:
    import importlib.util

    _docs_file = _src_root / "wet_mcp" / "sources" / "docs.py"
    _docs_spec = importlib.util.spec_from_file_location(
        "wet_mcp.sources.docs", _docs_file
    )
    _docs_mod = importlib.util.module_from_spec(_docs_spec)
    sys.modules["wet_mcp.sources.docs"] = _docs_mod
    _docs_spec.loader.exec_module(_docs_mod)

if "wet_mcp.db" not in sys.modules:
    import importlib.util

    _db_file = _src_root / "wet_mcp" / "db.py"
    _db_spec = importlib.util.spec_from_file_location("wet_mcp.db", _db_file)
    _db_mod = importlib.util.module_from_spec(_db_spec)
    sys.modules["wet_mcp.db"] = _db_mod
    _db_spec.loader.exec_module(_db_mod)

from wet_mcp.db import DocsDB


def test_upsert_library_normal_path(tmp_path):
    """Ensure normal upsert works as expected with the new validation."""
    db_file = tmp_path / "test.db"
    db = DocsDB(db_file)
    lib_id = db.upsert_library("react", docs_url="https://react.dev")
    assert lib_id is not None

    # Update
    lib_id2 = db.upsert_library("react", description="UI Library")
    assert lib_id == lib_id2

    lib = db.get_library("react")
    assert lib["description"] == "UI Library"
    assert lib["docs_url"] == "https://react.dev"

    # Update again
    db.upsert_library("react", registry="npm")
    lib = db.get_library("react")
    assert lib["registry"] == "npm"


def test_upsert_library_validation_internal(tmp_path):
    """Test validation logic by specifically targeting the internal check."""
    db_file = tmp_path / "test.db"
    db = DocsDB(db_file)
    db.upsert_library("testlib")  # Initial insert

    # We can use a trick: mock the `updates` list by patching `list` globally,
    # but that is dangerous.
    # Instead, let is look at `_now_ts` again.
    # What if we mock `_now_ts` to raise an exception?

    with patch(
        "wet_mcp.db._now_ts", side_effect=ValueError("Unauthorized update: mocked")
    ):
        with pytest.raises(ValueError, match="Unauthorized update: mocked"):
            db.upsert_library("testlib", description="new desc")
