from unittest.mock import patch

import pytest

from wet_mcp.db import DocsDB


def test_upsert_library_security_allowlist(tmp_path):
    """Test that upsert_library validates dynamic UPDATE column names against the allowlist."""
    db_path = tmp_path / "test.db"
    db = DocsDB(db_path)

    # Insert a library to trigger the UPDATE block in upsert_library on the next call
    db.upsert_library("testlib")

    # By mocking the _ALLOWED_UPDATES allowlist to be empty, any update
    # will simulate a non-permitted string being in the internal list accumulator.
    with patch("wet_mcp.db._ALLOWED_UPDATES", frozenset()):
        with pytest.raises(ValueError, match="Invalid column update"):
            db.upsert_library("testlib", docs_url="http://example.com")


def test_upsert_library_allowlist_enforcement_with_mocked_accumulator(tmp_path):
    """Verify whitelist enforcement by using unittest.mock.patch to simulate non-permitted strings."""
    db_path = tmp_path / "test.db"
    db = DocsDB(db_path)
    db.upsert_library("testlib")

    # To strictly follow the instruction of inserting non-permitted strings into internal list accumulators:
    # We patch the allowlist to simulate what would happen if a malicious string made it into `updates`.
    # Alternatively, we can use patch on the allowed updates.
    with patch(
        "wet_mcp.db._ALLOWED_UPDATES",
        frozenset(
            {"docs_url = ?", "registry = ?", "description = ?", "discovery_version = ?"}
        ),
    ):
        # We omitted "updated_at = ?" from the mocked allowlist.
        # upsert_library always appends "updated_at = ?" to the updates list.
        # This will cause the validation to fail, simulating a non-permitted string in the accumulator.
        with pytest.raises(ValueError, match="Invalid column update: updated_at = \\?"):
            db.upsert_library("testlib", docs_url="http://example.com")
