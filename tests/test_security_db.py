from unittest.mock import patch

import pytest

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
    assert lib is not None
    assert lib["description"] == "UI Library"
    assert lib["docs_url"] == "https://react.dev"

    # Update again
    db.upsert_library("react", registry="npm")
    lib = db.get_library("react")
    assert lib is not None
    assert lib["registry"] == "npm"


def test_upsert_library_validation_failure(tmp_path):
    """Verify that unauthorized update strings trigger ValueError."""
    db_file = tmp_path / "test.db"
    db = DocsDB(db_file)
    db.upsert_library("testlib")  # Initial insert

    # Inject an unauthorized string into the allowlist check by mocking the class attribute
    with patch.object(DocsDB, "_ALLOWED_LIBRARY_UPDATES", {"docs_url = ?"}):
        # Now registry = ? is unauthorized
        with pytest.raises(ValueError, match="Unauthorized update: registry = ?"):
            db.upsert_library("testlib", registry="npm")
