"""Comprehensive tests for DocsDB.get_best_version logic."""

import time

import pytest

from wet_mcp.db import DocsDB


@pytest.fixture
def db(tmp_path):
    db_path = tmp_path / "docs.db"
    return DocsDB(db_path, embedding_dims=0)


class TestGetBestVersionLogic:
    def test_exact_semantic_match(self, db):
        """Verify exact match for a version like '1.2.3'."""
        lib_id = db.upsert_library("testlib")
        ver_id = db.upsert_version(lib_id, "1.2.3")
        db.mark_version_indexed(ver_id, 1, 10)

        result = db.get_best_version(lib_id, "1.2.3")
        assert result is not None
        assert result["version"] == "1.2.3"

    def test_latest_tag_match(self, db):
        """Verify exact match for 'latest'."""
        lib_id = db.upsert_library("testlib")
        ver_id = db.upsert_version(lib_id, "latest")
        db.mark_version_indexed(ver_id, 1, 10)

        result = db.get_best_version(lib_id, "latest")
        assert result is not None
        assert result["version"] == "latest"

    def test_stable_tag_match(self, db):
        """Verify exact match for 'stable'."""
        lib_id = db.upsert_library("testlib")
        ver_id = db.upsert_version(lib_id, "stable")
        db.mark_version_indexed(ver_id, 1, 10)

        result = db.get_best_version(lib_id, "stable")
        assert result is not None
        assert result["version"] == "stable"

    def test_fallback_to_latest(self, db):
        """Verify that if '1.2.3' is missing, it falls back to 'latest'."""
        lib_id = db.upsert_library("testlib")
        ver_id = db.upsert_version(lib_id, "latest")
        db.mark_version_indexed(ver_id, 1, 10)

        result = db.get_best_version(lib_id, "1.2.3")
        assert result is not None
        assert result["version"] == "latest"

    def test_fallback_to_stable(self, db):
        """Verify that if '1.2.3' and 'latest' are missing, it falls back to 'stable'."""
        lib_id = db.upsert_library("testlib")
        ver_id = db.upsert_version(lib_id, "stable")
        db.mark_version_indexed(ver_id, 1, 10)

        # We didn't create 'latest', and we requested '1.2.3'
        result = db.get_best_version(lib_id, "1.2.3")
        assert result is not None
        assert result["version"] == "stable"

    def test_fallback_to_recent(self, db):
        """Verify fallback to the most recently indexed version if no tags match."""
        lib_id = db.upsert_library("testlib")

        # Indexed first
        ver1 = db.upsert_version(lib_id, "1.0.0")
        db.mark_version_indexed(ver1, 1, 10)

        time.sleep(0.1)  # Ensure different indexed_at

        # Indexed second (should be the recent fallback)
        ver2 = db.upsert_version(lib_id, "2.0.0")
        db.mark_version_indexed(ver2, 1, 10)

        # Request something else, and 'latest'/'stable' don't exist
        result = db.get_best_version(lib_id, "3.0.0")
        assert result is not None
        assert result["version"] == "2.0.0"

    def test_none_preferred_picks_best(self, db):
        """Verify that calling with None prefers 'latest' over 'stable' over recent."""
        lib_id = db.upsert_library("testlib")

        v_stable = db.upsert_version(lib_id, "stable")
        db.mark_version_indexed(v_stable, 1, 10)

        v_latest = db.upsert_version(lib_id, "latest")
        db.mark_version_indexed(v_latest, 1, 10)

        # Should pick 'latest'
        result = db.get_best_version(lib_id, None)
        assert result["version"] == "latest"

        # If 'latest' is gone, pick 'stable'
        db._conn.execute("DELETE FROM versions WHERE version = 'latest'")
        db._conn.commit()

        result = db.get_best_version(lib_id, None)
        assert result["version"] == "stable"

    def test_preferred_over_latest(self, db):
        """Verify that requested version is picked even if 'latest' exists."""
        lib_id = db.upsert_library("testlib")

        db.mark_version_indexed(db.upsert_version(lib_id, "latest"), 1, 10)
        db.mark_version_indexed(db.upsert_version(lib_id, "1.2.3"), 1, 10)

        result = db.get_best_version(lib_id, "1.2.3")
        assert result["version"] == "1.2.3"
