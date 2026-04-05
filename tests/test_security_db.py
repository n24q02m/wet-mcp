from unittest.mock import patch

import pytest

from wet_mcp.db import DocsDB


def test_upsert_library_allowlist_validation(tmp_path):
    """Verify that upsert_library rejects unauthorized update fragments."""
    db_path = tmp_path / "test.db"
    db = DocsDB(db_path)

    # Initial insert
    db.upsert_library("testlib", docs_url="http://example.com")

    # Now try to trigger an update with a mocked allowlist that is empty
    # This simulates an unauthorized fragment being added to 'updates' list.
    with patch("wet_mcp.db._ALLOWED_LIBRARY_UPDATES", frozenset()):
        with pytest.raises(ValueError, match="Unauthorized library update fragment"):
            db.upsert_library("testlib", docs_url="http://new.com")

    # Verify that it works normally when not patched
    db.upsert_library("testlib", docs_url="http://new.com")
    lib = db.get_library("testlib")
    assert lib is not None
    assert lib["docs_url"] == "http://new.com"
