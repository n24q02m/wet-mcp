from unittest.mock import patch

import pytest

from wet_mcp.db import DocsDB


def test_db_update_allowlist(tmp_path):
    db = DocsDB(tmp_path / "test.db")

    # Valid update should not raise
    lib_id = db.upsert_library(
        name="test-lib",
        docs_url="https://test.com/docs",
        registry="pypi",
        description="test desc",
    )
    assert lib_id is not None

    # Mock allowlist to be empty, so any update should raise ValueError
    with patch("wet_mcp.db._ALLOWED_UPDATES", frozenset()):
        with pytest.raises(ValueError, match="Invalid update field"):
            db.upsert_library(
                name="test-lib",
                docs_url="https://test.com/new-docs",
            )
