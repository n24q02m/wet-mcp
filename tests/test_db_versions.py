import time
from typing import Any

from wet_mcp.db import DocsDB


def test_get_best_version_complex_logic(tmp_path: Any) -> None:
    db_path = tmp_path / "test_versions.db"
    db = DocsDB(db_path, embedding_dims=0)

    lib_id = db.upsert_library(name="testlib")

    # Insert versions with controlled indexed_at times
    # v1.0 (oldest)
    v1_id = db.upsert_version(lib_id, version="1.0.0")
    db.mark_version_indexed(v1_id, page_count=1, chunk_count=1)

    time.sleep(0.1)  # Ensure distinct indexed_at
    # v2.0 (newer)
    v2_id = db.upsert_version(lib_id, version="2.0.0")
    db.mark_version_indexed(v2_id, page_count=1, chunk_count=1)

    time.sleep(0.1)
    # latest
    latest_id = db.upsert_version(lib_id, version="latest")
    db.mark_version_indexed(latest_id, page_count=1, chunk_count=1)

    time.sleep(0.1)
    # stable (newest indexed_at, but also 'stable' name)
    stable_id = db.upsert_version(lib_id, version="stable")
    db.mark_version_indexed(stable_id, page_count=1, chunk_count=1)

    # --- Test 1: Exact match ---
    res = db.get_best_version(lib_id, "1.0.0")
    assert res is not None
    assert res["version"] == "1.0.0"

    # --- Test 2: Preference for 'stable' when no target ---
    res = db.get_best_version(lib_id)
    assert res is not None
    assert res["version"] == "stable"

    # --- Test 3: Preference for 'stable' even if 'latest' is requested but missing? ---
    # Wait, if 'latest' is requested, it tries exact match for 'latest'.
    res = db.get_best_version(lib_id, "latest")
    assert res is not None
    assert res["version"] == "latest"

    # --- Test 4: Fallback to 'latest' when 'stable' is not indexed ---
    # We'll use a new library to avoid complexity with deleting from SQLite
    lib2_id = db.upsert_library(name="testlib2")
    v1_2 = db.upsert_version(lib2_id, version="1.0.0")
    db.mark_version_indexed(v1_2, 1, 1)
    time.sleep(0.1)
    v_latest_2 = db.upsert_version(lib2_id, version="latest")
    db.mark_version_indexed(v_latest_2, 1, 1)

    res = db.get_best_version(lib2_id)
    assert res is not None
    assert res["version"] == "latest"

    # --- Test 5: Fallback to most recent when 'stable' and 'latest' are missing ---
    lib3_id = db.upsert_library(name="testlib3")
    v1_3 = db.upsert_version(lib3_id, version="1.0.0")
    db.mark_version_indexed(v1_3, 1, 1)
    time.sleep(0.1)
    v2_3 = db.upsert_version(lib3_id, version="2.0.0")
    db.mark_version_indexed(v2_3, 1, 1)

    res = db.get_best_version(lib3_id)
    assert res is not None
    assert res["version"] == "2.0.0"  # most recently indexed

    # --- Test 6: Target not found fallback ---
    res = db.get_best_version(lib3_id, "9.9.9")
    assert res is not None
    assert res["version"] == "2.0.0"

    # --- Test 7: Target 'stable' explicitly, but not found ---
    # Should fallback to 'latest' then most recent
    lib4_id = db.upsert_library(name="testlib4")
    v_latest_4 = db.upsert_version(lib4_id, version="latest")
    db.mark_version_indexed(v_latest_4, 1, 1)

    res = db.get_best_version(lib4_id, "stable")
    assert res is not None
    assert res["version"] == "latest"

    db.close()


def test_get_best_version_unindexed(tmp_path: Any) -> None:
    db_path = tmp_path / "test_unindexed.db"
    db = DocsDB(db_path, embedding_dims=0)
    lib_id = db.upsert_library(name="unindexed")
    db.upsert_version(lib_id, version="1.0.0")  # status='pending'

    assert db.get_best_version(lib_id) is None
    assert db.get_best_version(lib_id, "1.0.0") is None
    db.close()


def test_get_best_version_branch_coverage(tmp_path: Any) -> None:
    db_path = tmp_path / "test_branches.db"
    db = DocsDB(db_path, embedding_dims=0)
    lib_id = db.upsert_library(name="branchlib")

    # 1. preferred_version == "stable" but not found
    # Should skip step 2 and go to 3 or 4.
    v1 = db.upsert_version(lib_id, version="1.0.0")
    db.mark_version_indexed(v1, 1, 1)

    res = db.get_best_version(lib_id, preferred_version="stable")
    assert res is not None
    assert res["version"] == "1.0.0"  # Fallback to most recent

    # 2. preferred_version == "latest" but not found
    # Should skip step 3 and go to 4.
    res = db.get_best_version(lib_id, preferred_version="latest")
    assert res is not None
    assert res["version"] == "1.0.0"  # Fallback to most recent

    db.close()
