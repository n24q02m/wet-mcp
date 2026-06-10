import time

import pytest

from wet_mcp.db import DocsDB


@pytest.fixture
def db(tmp_path):
    """Create a fresh DocsDB for each test."""
    db_path = tmp_path / "test_docs.db"
    db = DocsDB(db_path, embedding_dims=0)
    yield db
    db.close()


@pytest.fixture
def db_with_versions(db):
    """Setup a library with multiple versions."""
    lib_id = db.upsert_library(name="test-lib")

    # Version 1.0.0 (indexed first)
    v1 = db.upsert_version(lib_id, "1.0.0")
    db.mark_version_indexed(v1, 10, 100)
    time.sleep(0.01)  # Ensure different indexed_at

    # Version 'stable' (indexed second)
    v_stable = db.upsert_version(lib_id, "stable")
    db.mark_version_indexed(v_stable, 10, 100)
    time.sleep(0.01)

    # Version 2.0.0 (indexed third)
    v2 = db.upsert_version(lib_id, "2.0.0")
    db.mark_version_indexed(v2, 10, 100)
    time.sleep(0.01)

    # Version 'latest' (indexed fourth)
    v_latest = db.upsert_version(lib_id, "latest")
    db.mark_version_indexed(v_latest, 10, 100)

    return db, lib_id


class TestGetBestVersionHierarchy:
    def test_exact_match(self, db_with_versions):
        db, lib_id = db_with_versions
        # Target exact version
        ver = db.get_best_version(lib_id, preferred_version="1.0.0")
        assert ver is not None
        assert ver["version"] == "1.0.0"

    def test_fallback_to_stable(self, db_with_versions):
        db, lib_id = db_with_versions
        # No target, should pick 'stable' even if 'latest' is newer (indexed_at)
        ver = db.get_best_version(lib_id)
        assert ver is not None
        assert ver["version"] == "stable"

    def test_fallback_to_latest(self, db):
        # Case where 'stable' is missing
        lib_id = db.upsert_library(name="no-stable")
        db.upsert_version(lib_id, "1.0.0")
        db.mark_version_indexed(db.upsert_version(lib_id, "1.0.0"), 1, 1)

        v_latest = db.upsert_version(lib_id, "latest")
        db.mark_version_indexed(v_latest, 1, 1)

        ver = db.get_best_version(lib_id)
        assert ver is not None
        assert ver["version"] == "latest"

    def test_fallback_to_most_recent_indexed(self, db):
        # Case where both 'stable' and 'latest' are missing
        lib_id = db.upsert_library(name="only-semver")

        v1 = db.upsert_version(lib_id, "1.0.0")
        db.mark_version_indexed(v1, 1, 1)
        time.sleep(0.01)

        v2 = db.upsert_version(lib_id, "2.0.0")
        db.mark_version_indexed(v2, 1, 1)

        ver = db.get_best_version(lib_id)
        assert ver is not None
        assert ver["version"] == "2.0.0"  # Most recently indexed

    def test_nonexistent_library(self, db):
        ver = db.get_best_version("nonexistent")
        assert ver is None

    def test_no_indexed_versions(self, db):
        lib_id = db.upsert_library(name="unindexed")
        db.upsert_version(lib_id, "1.0.0")  # Not indexed
        ver = db.get_best_version(lib_id)
        assert ver is None
