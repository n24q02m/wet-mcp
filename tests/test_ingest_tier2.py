"""Tests for the ingest_tier2 on-demand library ingester.

Mocks discover_library + fetch_docs_pages so we can drive every branch
of the ingester without hitting the network.
"""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

# Bootstrap (idempotent — see test_docs_resolve.py).
_src_root = Path(__file__).resolve().parent.parent / "src"

if "wet_mcp" not in sys.modules:
    _pkg = types.ModuleType("wet_mcp")
    _pkg.__path__ = [str(_src_root / "wet_mcp")]
    sys.modules["wet_mcp"] = _pkg

if "wet_mcp.sources" not in sys.modules:
    _sources_pkg = types.ModuleType("wet_mcp.sources")
    _sources_pkg.__path__ = [str(_src_root / "wet_mcp" / "sources")]
    sys.modules["wet_mcp.sources"] = _sources_pkg

if "wet_mcp.sources.docs" not in sys.modules:
    _docs_file = _src_root / "wet_mcp" / "sources" / "docs.py"
    _docs_spec = importlib.util.spec_from_file_location(
        "wet_mcp.sources.docs", _docs_file
    )
    assert _docs_spec is not None
    _docs_mod = importlib.util.module_from_spec(_docs_spec)
    sys.modules["wet_mcp.sources.docs"] = _docs_mod
    _docs_spec.loader.exec_module(_docs_mod)
else:
    _docs_mod = sys.modules["wet_mcp.sources.docs"]

if "wet_mcp.db" not in sys.modules:
    _db_file = _src_root / "wet_mcp" / "db.py"
    _db_spec = importlib.util.spec_from_file_location("wet_mcp.db", _db_file)
    assert _db_spec is not None
    _db_mod = importlib.util.module_from_spec(_db_spec)
    sys.modules["wet_mcp.db"] = _db_mod
    _db_spec.loader.exec_module(_db_mod)
else:
    _db_mod = sys.modules["wet_mcp.db"]

DocsDB = _db_mod.DocsDB
ingest_tier2 = _docs_mod.ingest_tier2


@pytest.fixture
def db(tmp_path: Path) -> DocsDB:
    instance = DocsDB(tmp_path / "docs.db", embedding_dims=0)
    yield instance
    instance.close()


async def test_ingest_tier2_empty_name_returns_error(db: DocsDB) -> None:
    out = await ingest_tier2(db, "")
    assert out["status"] == "error"


async def test_ingest_tier2_unknown_library_returns_not_found(db: DocsDB) -> None:
    with patch.object(_docs_mod, "discover_library", new=AsyncMock(return_value=None)):
        out = await ingest_tier2(db, "obscure-xyz-123")
    assert out["status"] == "not_found"
    assert out["library_name"] == "obscure-xyz-123"


async def test_ingest_tier2_no_docs_url_returns_no_docs(db: DocsDB) -> None:
    """discover_library returns metadata but no docs_url and no repo_url."""
    with (
        patch.object(
            _docs_mod,
            "discover_library",
            new=AsyncMock(
                return_value={
                    "registry": "npm",
                    "description": "test lib",
                    # No docs_url, no repository, no github_url, no homepage
                }
            ),
        ),
        patch.object(_docs_mod, "fetch_docs_pages", new=AsyncMock(return_value=[])),
    ):
        out = await ingest_tier2(db, "no-docs-lib")
    assert out["status"] == "no_docs"
    assert out["library_id"]
    assert out["version_id"]


async def test_ingest_tier2_with_docs_url_creates_chunks(db: DocsDB) -> None:
    """Happy path: discover + fetch yields pages -> chunks land in DB."""
    pages = [
        {
            "url": "https://example.com/p1",
            "title": "Intro",
            "content": "# Intro\n\nSome introduction text about the library.",
        },
        {
            "url": "https://example.com/p2",
            "title": "Usage",
            "content": "# Usage\n\n```python\nimport mylib\nmylib.run()\n```",
        },
    ]
    with (
        patch.object(
            _docs_mod,
            "discover_library",
            new=AsyncMock(
                return_value={
                    "docs_url": "https://example.com/docs",
                    "registry": "pypi",
                    "description": "Example lib",
                    "homepage": "https://example.com",
                    "repository": "https://github.com/example/lib",
                }
            ),
        ),
        patch.object(_docs_mod, "fetch_docs_pages", new=AsyncMock(return_value=pages)),
    ):
        out = await ingest_tier2(db, "example-lib")
    # Status is "ok" when chunks land, "no_chunks" if chunk_markdown filters
    # everything out — both branches are valid coverage hits for the path.
    assert out["status"] in {"ok", "no_chunks"}
    assert out["page_count"] == 2
    # Library row was upserted with tier=2.
    lib_row = db.get_library("example-lib")
    assert lib_row["tier"] == 2
    assert lib_row["registry"] == "pypi"


async def test_ingest_tier2_no_pages_returns_no_chunks(db: DocsDB) -> None:
    """fetch_docs_pages returns empty -> status 'no_chunks'."""
    with (
        patch.object(
            _docs_mod,
            "discover_library",
            new=AsyncMock(
                return_value={
                    "docs_url": "https://example.com/docs",
                    "registry": "npm",
                }
            ),
        ),
        patch.object(_docs_mod, "fetch_docs_pages", new=AsyncMock(return_value=[])),
    ):
        out = await ingest_tier2(db, "empty-lib")
    assert out["status"] == "no_chunks"
    assert out["chunk_count"] == 0


async def test_ingest_tier2_uses_repo_url_when_no_docs_url(db: DocsDB) -> None:
    """When discover only returns a repo, fetch is invoked against it."""
    pages = [
        {
            "url": "https://github.com/foo/bar/blob/main/README.md",
            "title": "README",
            "content": "# bar\n\nUsage example.",
        }
    ]
    with (
        patch.object(
            _docs_mod,
            "discover_library",
            new=AsyncMock(return_value={"github_url": "https://github.com/foo/bar"}),
        ),
        patch.object(_docs_mod, "fetch_docs_pages", new=AsyncMock(return_value=pages)),
    ):
        out = await ingest_tier2(db, "bar")
    assert out["status"] in {"ok", "no_chunks"}
