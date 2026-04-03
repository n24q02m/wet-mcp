import importlib.util
import sys
import types
from pathlib import Path
from unittest.mock import patch

import pytest

_src_root = Path(__file__).resolve().parent.parent / "src"

# Bootstrap modules directly to avoid numpy/crawl4ai dependency
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
DISCOVERY_VERSION = _docs_mod.DISCOVERY_VERSION


@pytest.fixture
def db(tmp_path):
    """Create a fresh DocsDB for each test."""
    db_path = tmp_path / "test_upsert.db"
    db = DocsDB(db_path, embedding_dims=0)
    yield db
    db.close()


class TestUpsertLibraryComprehensive:
    """Comprehensive tests for DocsDB.upsert_library."""

    def test_upsert_library_new(self, db):
        """Test inserting a completely new library."""
        with patch("wet_mcp.db._now_ts", return_value=123.456):
            lib_id = db.upsert_library(
                name="BrandNew",
                docs_url="https://docs.brandnew.com",
                registry="pypi",
                description="A brand new library",
            )

        assert len(lib_id) == 12
        lib = db.get_library("brandnew")
        assert lib["id"] == lib_id
        assert lib["name"] == "brandnew"
        assert lib["docs_url"] == "https://docs.brandnew.com"
        assert lib["registry"] == "pypi"
        assert lib["description"] == "A brand new library"
        assert lib["discovery_version"] == DISCOVERY_VERSION
        assert lib["created_at"] == 123.456
        assert lib["updated_at"] == 123.456

    def test_upsert_library_update_all_fields(self, db):
        """Test updating all fields of an existing library."""
        initial_id = db.upsert_library(name="updatelib")

        with (
            patch("wet_mcp.db.DISCOVERY_VERSION", 999),
            patch("wet_mcp.db._now_ts", return_value=789.0),
        ):
            updated_id = db.upsert_library(
                name="updatelib",
                docs_url="https://newdocs.com",
                registry="npm",
                description="Updated description",
            )

        assert initial_id == updated_id
        lib = db.get_library("updatelib")
        assert lib["docs_url"] == "https://newdocs.com"
        assert lib["registry"] == "npm"
        assert lib["description"] == "Updated description"
        assert lib["discovery_version"] == 999
        assert lib["updated_at"] == 789.0

    def test_upsert_library_partial_updates(self, db):
        """Test updating fields one by one."""
        db.upsert_library(
            name="partial",
            docs_url="https://old.com",
            registry="pypi",
            description="old",
        )

        # Update only docs_url
        db.upsert_library(name="partial", docs_url="https://new.com")
        lib = db.get_library("partial")
        assert lib["docs_url"] == "https://new.com"
        assert lib["registry"] == "pypi"
        assert lib["description"] == "old"

        # Update only registry
        db.upsert_library(name="partial", registry="npm")
        lib = db.get_library("partial")
        assert lib["registry"] == "npm"
        assert lib["docs_url"] == "https://new.com"
        assert lib["description"] == "old"

        # Update only description
        db.upsert_library(name="partial", description="new")
        lib = db.get_library("partial")
        assert lib["description"] == "new"
        assert lib["registry"] == "npm"
        assert lib["docs_url"] == "https://new.com"

    def test_upsert_library_normalization(self, db):
        """Test name normalization (lowercase and strip)."""
        id1 = db.upsert_library(name="  MixedCaseLib  ")
        id2 = db.upsert_library(name="mixedcaselib")

        assert id1 == id2
        lib = db.get_library("mixedcaselib")
        assert lib["name"] == "mixedcaselib"

    def test_upsert_library_discovery_version_and_timestamp_always_updated(self, db):
        """Verify discovery_version and updated_at are updated even if other fields aren't."""
        db.upsert_library(name="timelib", docs_url="https://a.com")
        initial_lib = db.get_library("timelib")

        with (
            patch("wet_mcp.db.DISCOVERY_VERSION", DISCOVERY_VERSION + 1),
            patch("wet_mcp.db._now_ts", return_value=initial_lib["updated_at"] + 100),
        ):
            db.upsert_library(name="timelib")

        updated_lib = db.get_library("timelib")
        assert updated_lib["discovery_version"] == DISCOVERY_VERSION + 1
        assert updated_lib["updated_at"] == initial_lib["updated_at"] + 100
        assert updated_lib["created_at"] == initial_lib["created_at"]
