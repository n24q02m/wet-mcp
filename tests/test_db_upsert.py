import importlib.util
import sys
import types
from pathlib import Path
from unittest.mock import patch

import pytest

# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------
_src_root = Path(__file__).resolve().parent.parent / "src"

if "wet_mcp" not in sys.modules:
    _pkg = types.ModuleType("wet_mcp")
    _pkg.__path__ = [str(_src_root / "wet_mcp")]
    sys.modules["wet_mcp"] = _pkg

if "wet_mcp.sources" not in sys.modules:
    _sources_pkg = types.ModuleType("wet_mcp.sources")
    _sources_pkg.__path__ = [str(_src_root / "wet_mcp" / "sources")]
    sys.modules["wet_mcp.sources"] = _sources_pkg

_docs_file = _src_root / "wet_mcp" / "sources" / "docs.py"
_docs_spec = importlib.util.spec_from_file_location("wet_mcp.sources.docs", _docs_file)
assert _docs_spec is not None
_docs_mod = importlib.util.module_from_spec(_docs_spec)
sys.modules["wet_mcp.sources.docs"] = _docs_mod
_docs_spec.loader.exec_module(_docs_mod)

_db_file = _src_root / "wet_mcp" / "db.py"
_db_spec = importlib.util.spec_from_file_location("wet_mcp.db", _db_file)
assert _db_spec is not None
_db_mod = importlib.util.module_from_spec(_db_spec)
sys.modules["wet_mcp.db"] = _db_mod
_db_spec.loader.exec_module(_db_mod)

DocsDB = _db_mod.DocsDB


@pytest.fixture
def db(tmp_path):
    db_path = tmp_path / "test_upsert.db"
    db = DocsDB(db_path, embedding_dims=0)
    yield db
    db.close()


class TestUpsertLibraryComprehensive:
    def test_upsert_insert_path(self, db):
        """Test creating a new library."""
        with (
            patch.object(_db_mod, "DISCOVERY_VERSION", 42),
            patch.object(_db_mod, "_now_ts", return_value=1000.0),
        ):
            lib_id = db.upsert_library(
                name="NewLib",
                docs_url="https://new.com",
                registry="pypi",
                description="A new library",
            )

        lib = db.get_library("newlib")
        assert lib["id"] == lib_id
        assert lib["name"] == "newlib"
        assert lib["docs_url"] == "https://new.com"
        assert lib["registry"] == "pypi"
        assert lib["description"] == "A new library"
        assert lib["discovery_version"] == 42
        assert lib["created_at"] == 1000.0
        assert lib["updated_at"] == 1000.0

    def test_upsert_update_path(self, db):
        """Test updating an existing library."""
        # Initial insert
        with patch.object(_db_mod, "_now_ts", return_value=1000.0):
            lib_id = db.upsert_library(name="mylib", docs_url="https://old.com")

        # Update
        with (
            patch.object(_db_mod, "DISCOVERY_VERSION", 43),
            patch.object(_db_mod, "_now_ts", return_value=2000.0),
        ):
            lib_id2 = db.upsert_library(
                name=" MyLib ",
                docs_url="https://new.com",
                registry="npm",
                description="Updated desc",
            )

        assert lib_id == lib_id2
        lib = db.get_library("mylib")
        assert lib["docs_url"] == "https://new.com"
        assert lib["registry"] == "npm"
        assert lib["description"] == "Updated desc"
        assert lib["discovery_version"] == 43
        assert lib["created_at"] == 1000.0
        assert lib["updated_at"] == 2000.0

    def test_upsert_update_stamps_always(self, db):
        """Even if no fields change, discovery_version and updated_at are updated."""
        # Initial insert
        with (
            patch.object(_db_mod, "DISCOVERY_VERSION", 1),
            patch.object(_db_mod, "_now_ts", return_value=1000.0),
        ):
            db.upsert_library(name="test")

        # Call again with same name but different discovery_version/time
        with (
            patch.object(_db_mod, "DISCOVERY_VERSION", 2),
            patch.object(_db_mod, "_now_ts", return_value=2000.0),
        ):
            db.upsert_library(name="test")

        lib = db.get_library("test")
        assert lib["discovery_version"] == 2
        assert lib["updated_at"] == 2000.0

    def test_upsert_security_allowlist(self, db):
        """Test that unauthorized updates are blocked."""
        db.upsert_library(name="test")

        # Mock _ALLOWED_UPDATES to be empty
        with patch.object(_db_mod, "_ALLOWED_UPDATES", frozenset()):
            with pytest.raises(ValueError, match="Unauthorized library update"):
                db.upsert_library(name="test", docs_url="https://evil.com")

    def test_name_normalization(self, db):
        """Test that names are lowercased and stripped."""
        db.upsert_library(name="  UpperCaseLib  ")
        lib = db.get_library("uppercaselib")
        assert lib is not None
        assert lib["name"] == "uppercaselib"


def test_upsert_insert_without_optional_fields(db):
    """Test creating a new library without optional fields."""
    with (
        patch.object(_db_mod, "DISCOVERY_VERSION", 42),
        patch.object(_db_mod, "_now_ts", return_value=1000.0),
    ):
        lib_id = db.upsert_library(name="MinimalLib")

    lib = db.get_library("minimallib")
    assert lib["id"] == lib_id
    assert lib["docs_url"] is None
    assert lib["registry"] is None
    assert lib["description"] is None
