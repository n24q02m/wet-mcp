"""Tests for src/wet_mcp/db.py — DocsDB with FTS5 hybrid search.

Covers library/version CRUD, FTS5 search scoring (phrase/AND/OR tiers),
JSONL export/import, edge cases (Unicode, empty queries, special characters),
chunk quality scoring, and cross-chunk context retrieval.
"""

import json

import pytest

from wet_mcp.db import DocsDB, _build_fts_queries, _chunk_quality_score


@pytest.fixture
def db(tmp_path):
    """Create a fresh DocsDB for each test."""
    db_path = tmp_path / "test_docs.db"
    db = DocsDB(db_path, embedding_dims=0)
    yield db
    db.close()


@pytest.fixture
def db_with_data(db):
    """DB pre-populated with a library, version, and chunks."""
    lib_id = db.upsert_library(
        name="fastapi",
        docs_url="https://fastapi.tiangolo.com",
        registry="pypi",
        description="Modern web framework for Python",
    )
    ver_id = db.upsert_version(lib_id, version="0.100.0")
    chunks = [
        {
            "content": "FastAPI is a modern, fast web framework for building APIs with Python 3.8+.",
            "title": "Introduction",
            "url": "https://fastapi.tiangolo.com/",
            "heading_path": "Introduction",
            "chunk_index": 0,
        },
        {
            "content": "To create a route, use the @app.get() decorator. Path parameters are defined in the URL path.",
            "title": "Routing",
            "url": "https://fastapi.tiangolo.com/tutorial/first-steps/",
            "heading_path": "Tutorial > First Steps",
            "chunk_index": 1,
        },
        {
            "content": "Dependency injection in FastAPI uses the Depends() function. Dependencies can be nested.",
            "title": "Dependencies",
            "url": "https://fastapi.tiangolo.com/tutorial/dependencies/",
            "heading_path": "Tutorial > Dependencies",
            "chunk_index": 2,
        },
        {
            "content": "WebSocket endpoints use @app.websocket() decorator for real-time bidirectional communication.",
            "title": "WebSockets",
            "url": "https://fastapi.tiangolo.com/advanced/websockets/",
            "heading_path": "Advanced > WebSockets",
            "chunk_index": 3,
        },
    ]
    db.add_chunks(ver_id, lib_id, chunks)
    db.mark_version_indexed(ver_id, page_count=4, chunk_count=4)
    return db, lib_id, ver_id


# -----------------------------------------------------------------------
# Library CRUD
# -----------------------------------------------------------------------


class TestLibraryCRUD:
    def test_upsert_and_get_library(self, db):
        """Create a library and retrieve it."""
        lib_id = db.upsert_library(
            name="React",
            docs_url="https://react.dev",
            registry="npm",
            description="UI library",
        )
        assert lib_id
        lib = db.get_library("react")  # name is lowercased
        assert lib is not None
        assert lib["name"] == "react"
        assert lib["docs_url"] == "https://react.dev"
        assert lib["registry"] == "npm"

    def test_upsert_updates_existing(self, db):
        """Upserting same name updates fields, keeps same ID."""
        id1 = db.upsert_library(name="react", docs_url="https://old.dev")
        id2 = db.upsert_library(name="React", docs_url="https://react.dev")
        assert id1 == id2
        lib = db.get_library("react")
        assert lib["docs_url"] == "https://react.dev"

    def test_get_nonexistent_library(self, db):
        assert db.get_library("nonexistent") is None

    def test_list_libraries_empty(self, db):
        assert db.list_libraries() == []

    def test_list_libraries_with_data(self, db_with_data):
        db = db_with_data[0]
        libs = db.list_libraries()
        assert len(libs) == 1
        assert libs[0]["name"] == "fastapi"
        assert libs[0]["total_chunks"] == 4

    def test_remove_library(self, db_with_data):
        db = db_with_data[0]
        assert db.remove_library("fastapi") is True
        assert db.get_library("fastapi") is None
        assert db.list_libraries() == []

    def test_remove_nonexistent(self, db):
        assert db.remove_library("ghost") is False

    def test_library_name_normalization(self, db):
        """Names are lowercased and stripped."""
        db.upsert_library(name="  PyTorch  ")
        lib = db.get_library("pytorch")
        assert lib is not None
        assert lib["name"] == "pytorch"


# -----------------------------------------------------------------------
# Version management
# -----------------------------------------------------------------------


class TestVersionManagement:
    def test_upsert_version(self, db):
        lib_id = db.upsert_library(name="react")
        ver_id = db.upsert_version(lib_id, version="18.2.0")
        assert ver_id
        # Same version returns same ID
        ver_id2 = db.upsert_version(lib_id, version="18.2.0")
        assert ver_id == ver_id2

    def test_get_best_version_exact(self, db_with_data):
        db, lib_id, ver_id = db_with_data
        ver = db.get_best_version(lib_id, "0.100.0")
        assert ver is not None
        assert ver["version"] == "0.100.0"

    def test_get_best_version_latest(self, db_with_data):
        db, lib_id, _ = db_with_data
        ver = db.get_best_version(lib_id)
        assert ver is not None
        assert ver["status"] == "indexed"

    def test_get_best_version_nonexistent(self, db_with_data):
        db, lib_id, _ = db_with_data
        ver = db.get_best_version(lib_id, "99.99.99")
        # Should fallback to latest indexed
        assert ver is not None

    def test_mark_version_indexed(self, db):
        lib_id = db.upsert_library(name="test")
        ver_id = db.upsert_version(lib_id, version="1.0")
        db.mark_version_indexed(ver_id, page_count=5, chunk_count=20)
        ver = db.get_best_version(lib_id, "1.0")
        assert ver["status"] == "indexed"
        assert ver["page_count"] == 5
        assert ver["chunk_count"] == 20


# -----------------------------------------------------------------------
# Chunks & Search
# -----------------------------------------------------------------------


class TestSearch:
    def test_fts_search_basic(self, db_with_data):
        """FTS5 search returns relevant results."""
        db = db_with_data[0]
        results = db.search(query="route decorator", library_name="fastapi")
        assert len(results) > 0
        # The routing chunk should be most relevant
        assert any("route" in r["content"].lower() for r in results)

    def test_fts_search_returns_scored(self, db_with_data):
        """All results have a score > 0."""
        db = db_with_data[0]
        results = db.search(query="dependencies", library_name="fastapi")
        for r in results:
            assert "score" in r
            assert r["score"] > 0

    def test_fts_search_limit(self, db_with_data):
        """Limit parameter is respected."""
        db = db_with_data[0]
        results = db.search(query="FastAPI", library_name="fastapi", limit=2)
        assert len(results) <= 2

    def test_fts_search_no_results(self, db_with_data):
        """Query with no matches returns empty."""
        db = db_with_data[0]
        results = db.search(query="xyznonexistentterm", library_name="fastapi")
        assert results == []

    def test_fts_search_unknown_library(self, db_with_data):
        """Search for nonexistent library returns empty."""
        db = db_with_data[0]
        results = db.search(query="anything", library_name="nonexistent")
        assert results == []

    def test_fts_search_special_characters(self, db):
        """FTS handles special characters gracefully."""
        lib_id = db.upsert_library(name="test")
        ver_id = db.upsert_version(lib_id)
        db.add_chunks(
            ver_id,
            lib_id,
            [
                {"content": "Use @app.get('/items/{item_id}') for path params."},
                {"content": "Query: ?skip=0&limit=10 supports pagination."},
            ],
        )
        # Should not raise even with FTS-hostile characters
        results = db.search(query="@app.get path params", library_name="test")
        assert isinstance(results, list)

    def test_fts_search_unicode(self, db):
        """FTS handles Unicode content properly."""
        lib_id = db.upsert_library(name="i18n-lib")
        ver_id = db.upsert_version(lib_id)
        db.add_chunks(
            ver_id,
            lib_id,
            [
                {"content": "Internationalisation: Bonjour, Hola, Hallo, Xin chao"},
                {"content": "Japanese: Sumimasen, arigatou gozaimasu"},
            ],
        )
        results = db.search(query="Bonjour", library_name="i18n-lib")
        assert len(results) > 0
        assert "Bonjour" in results[0]["content"]

    def test_search_result_format(self, db_with_data):
        """Each result has all expected fields."""
        db = db_with_data[0]
        results = db.search(query="FastAPI", library_name="fastapi")
        assert len(results) > 0
        r = results[0]
        assert "content" in r
        assert "title" in r
        assert "url" in r
        assert "heading_path" in r
        assert "library" in r
        assert "score" in r
        assert r["library"] == "fastapi"

    def test_search_with_version_filter(self, db_with_data):
        """Search filtered to specific version."""
        db, lib_id, _ = db_with_data
        # Add another version with different content
        ver2_id = db.upsert_version(lib_id, "0.99.0")
        db.add_chunks(
            ver2_id,
            lib_id,
            [
                {"content": "Old deprecated routing system uses @app.route()."},
            ],
        )
        db.mark_version_indexed(ver2_id, 1, 1)

        # Search v0.99.0 should find "deprecated"
        results = db.search(
            query="deprecated routing",
            library_name="fastapi",
            version="0.99.0",
        )
        assert any("deprecated" in r["content"].lower() for r in results)


class TestRecencyScoring:
    """Verify scoring components (recency decay removed — docs chunks
    share the same indexing timestamp, making recency meaningless).

    Tests now cover chunk quality scoring and phrase tier queries.
    """

    def test_chunk_quality_with_code(self):
        """Chunks with code blocks get higher quality scores."""
        code_content = "Example:\n```python\napp = FastAPI()\n```\nSome text after."
        no_code = "This is plain documentation text without code examples."
        assert _chunk_quality_score(code_content) > _chunk_quality_score(no_code)

    def test_chunk_quality_long_content(self):
        """Longer content gets moderate quality boost."""
        short = "Short text."
        medium = "x " * 150  # ~300 chars
        long = "x " * 300  # ~600 chars
        assert _chunk_quality_score(long) >= _chunk_quality_score(medium)
        assert _chunk_quality_score(medium) >= _chunk_quality_score(short)

    def test_chunk_quality_link_heavy_penalty(self):
        """Link-heavy TOC chunks are penalized."""
        toc = "\n".join(f"- [Link {i}](https://example.com/{i})" for i in range(10))
        content = "This is real documentation with examples and explanations. " * 5
        assert _chunk_quality_score(content) > _chunk_quality_score(toc)


class TestPhraseTierQueries:
    """Verify the tiered FTS5 query builder (PHRASE > AND > OR)."""

    def test_single_word(self):
        """Single word returns a single prefix query."""
        queries = _build_fts_queries("routing")
        assert len(queries) == 1
        assert queries[0] == '"routing"*'

    def test_multi_word_tiers(self):
        """Multi-word query returns 3 tiers: PHRASE, AND, OR."""
        queries = _build_fts_queries("path parameters")
        assert len(queries) == 3
        # Tier 0: exact phrase
        assert queries[0] == '"path parameters"'
        # Tier 1: AND
        assert "AND" in queries[1]
        # Tier 2: OR
        assert "OR" in queries[2]

    def test_empty_query(self):
        """Empty query returns no tiers."""
        assert _build_fts_queries("") == []
        assert _build_fts_queries("   ") == []

    def test_quotes_escaped(self):
        """Double quotes in input are escaped."""
        queries = _build_fts_queries('say "hello"')
        # Should not break FTS syntax
        assert len(queries) == 3

    def test_phrase_search_ranks_higher(self, db_with_data):
        """Exact phrase match should rank higher than scattered terms."""
        db = db_with_data[0]
        # "path parameters" appears together in routing chunk
        results = db.search(query="path parameters", library_name="fastapi")
        assert len(results) > 0
        # First result should contain both words
        assert "path" in results[0]["content"].lower()


class TestCrossChunkContext:
    """Verify adjacent chunk retrieval in search results."""

    def test_context_before_and_after(self, db):
        """Search results include adjacent chunk content."""
        lib_id = db.upsert_library(name="ctx-test")
        ver_id = db.upsert_version(lib_id)
        chunks = [
            {
                "content": "Chapter 1: Introduction to the framework.",
                "url": "https://example.com/docs",
                "chunk_index": 0,
            },
            {
                "content": "Chapter 2: Routing and path parameters.",
                "url": "https://example.com/docs",
                "chunk_index": 1,
            },
            {
                "content": "Chapter 3: Dependency injection patterns.",
                "url": "https://example.com/docs",
                "chunk_index": 2,
            },
        ]
        db.add_chunks(ver_id, lib_id, chunks)

        results = db.search(query="routing path", library_name="ctx-test")
        assert len(results) > 0
        # Chunk 1 should match "routing path"
        routing_result = next(
            (r for r in results if "routing" in r["content"].lower()), None
        )
        assert routing_result is not None
        # Should have context from adjacent chunks
        assert "context_before" in routing_result
        assert "Introduction" in routing_result["context_before"]
        assert "context_after" in routing_result
        assert "Dependency" in routing_result["context_after"]

    def test_first_chunk_no_context_before(self, db):
        """First chunk has no context_before."""
        lib_id = db.upsert_library(name="first-chunk")
        ver_id = db.upsert_version(lib_id)
        chunks = [
            {
                "content": "First chapter about routing setup.",
                "url": "https://example.com/page",
                "chunk_index": 0,
            },
            {
                "content": "Second chapter about middleware.",
                "url": "https://example.com/page",
                "chunk_index": 1,
            },
        ]
        db.add_chunks(ver_id, lib_id, chunks)

        results = db.search(query="routing setup", library_name="first-chunk")
        assert len(results) > 0
        first = results[0]
        assert "context_before" not in first
        assert "context_after" in first

    def test_last_chunk_no_context_after(self, db):
        """Last chunk has no context_after."""
        lib_id = db.upsert_library(name="last-chunk")
        ver_id = db.upsert_version(lib_id)
        chunks = [
            {
                "content": "Previous chapter about configuration.",
                "url": "https://example.com/page",
                "chunk_index": 0,
            },
            {
                "content": "Final chapter about deployment and routing.",
                "url": "https://example.com/page",
                "chunk_index": 1,
            },
        ]
        db.add_chunks(ver_id, lib_id, chunks)

        results = db.search(query="deployment routing", library_name="last-chunk")
        assert len(results) > 0
        last = next((r for r in results if "deployment" in r["content"].lower()), None)
        assert last is not None
        assert "context_before" in last
        assert "context_after" not in last


class TestChunksCRUD:
    def test_add_and_clear_chunks(self, db):
        lib_id = db.upsert_library(name="test")
        ver_id = db.upsert_version(lib_id)
        count = db.add_chunks(
            ver_id,
            lib_id,
            [
                {"content": "chunk 1"},
                {"content": "chunk 2"},
                {"content": "chunk 3"},
            ],
        )
        assert count == 3
        cleared = db.clear_version_chunks(ver_id)
        assert cleared == 3

    def test_add_chunks_minimal_fields(self, db):
        """Chunks only require content field."""
        lib_id = db.upsert_library(name="minimal")
        ver_id = db.upsert_version(lib_id)
        count = db.add_chunks(ver_id, lib_id, [{"content": "just content"}])
        assert count == 1
        results = db.search(query="just content", library_name="minimal")
        assert len(results) == 1
        assert results[0]["content"] == "just content"


# -----------------------------------------------------------------------
# JSONL Export / Import
# -----------------------------------------------------------------------


class TestJSONLSync:
    def test_export_empty_db(self, db):
        """Exporting empty DB returns empty string."""
        assert db.export_jsonl() == ""

    def test_export_roundtrip(self, db_with_data, tmp_path):
        """Export from one DB, import into another — same data."""
        src_db = db_with_data[0]
        jsonl = src_db.export_jsonl()
        assert jsonl.strip()

        # Parse and verify structure
        lines = [json.loads(line) for line in jsonl.strip().split("\n")]
        types = [item["_type"] for item in lines]
        assert "library" in types
        assert "version" in types
        assert "chunk" in types

        # Import into fresh DB
        dst_db = DocsDB(tmp_path / "dst.db", embedding_dims=0)
        try:
            stats = dst_db.import_jsonl(jsonl, mode="replace")
            assert stats["libraries"] == 1
            assert stats["versions"] == 1
            assert stats["chunks"] == 4

            # Verify data is searchable
            results = dst_db.search(query="route decorator", library_name="fastapi")
            assert len(results) > 0
        finally:
            dst_db.close()

    def test_import_merge_skips_existing(self, db_with_data, tmp_path):
        """Merge mode skips existing records."""
        src_db = db_with_data[0]
        jsonl = src_db.export_jsonl()

        dst_db = DocsDB(tmp_path / "dst.db", embedding_dims=0)
        try:
            # First import
            stats1 = dst_db.import_jsonl(jsonl, mode="merge")
            assert stats1["libraries"] == 1
            assert stats1["skipped"] == 0

            # Second import — all should be skipped
            stats2 = dst_db.import_jsonl(jsonl, mode="merge")
            assert stats2["libraries"] == 0
            assert stats2["skipped"] > 0
        finally:
            dst_db.close()

    def test_import_replace_clears_first(self, db_with_data, tmp_path):
        """Replace mode clears existing data before import."""
        src_db = db_with_data[0]
        jsonl = src_db.export_jsonl()

        dst_db = DocsDB(tmp_path / "dst.db", embedding_dims=0)
        try:
            # First import
            dst_db.import_jsonl(jsonl, mode="replace")

            # Second import with replace — should not fail
            stats = dst_db.import_jsonl(jsonl, mode="replace")
            assert stats["libraries"] == 1
            assert stats["chunks"] == 4
        finally:
            dst_db.close()


# -----------------------------------------------------------------------
# Edge cases
# -----------------------------------------------------------------------


class TestEdgeCases:
    def test_close_and_reopen(self, tmp_path):
        """Data persists after close and reopen."""
        db_path = tmp_path / "persist.db"
        db1 = DocsDB(db_path, embedding_dims=0)
        db1.upsert_library(name="persist-test", docs_url="https://example.com")
        db1.close()

        db2 = DocsDB(db_path, embedding_dims=0)
        lib = db2.get_library("persist-test")
        assert lib is not None
        assert lib["docs_url"] == "https://example.com"
        db2.close()

    def test_empty_query(self, db_with_data):
        """Empty query should not crash."""
        db = db_with_data[0]
        results = db.search(query="", library_name="fastapi")
        assert isinstance(results, list)

    def test_single_word_query(self, db_with_data):
        """Single word queries work."""
        db = db_with_data[0]
        results = db.search(query="WebSocket", library_name="fastapi")
        assert len(results) > 0

    def test_multiple_libraries(self, db):
        """Search is scoped to specified library."""
        # Library A
        id_a = db.upsert_library(name="lib-a")
        ver_a = db.upsert_version(id_a)
        db.add_chunks(
            ver_a,
            id_a,
            [
                {"content": "Alpha library routing system."},
            ],
        )
        # Library B
        id_b = db.upsert_library(name="lib-b")
        ver_b = db.upsert_version(id_b)
        db.add_chunks(
            ver_b,
            id_b,
            [
                {"content": "Beta library routing system."},
            ],
        )

        results_a = db.search(query="routing", library_name="lib-a")
        results_b = db.search(query="routing", library_name="lib-b")

        assert all(r["library"] == "lib-a" for r in results_a)
        assert all(r["library"] == "lib-b" for r in results_b)

    def test_remove_library_cascades(self, db):
        """Removing a library deletes all versions and chunks."""
        lib_id = db.upsert_library(name="cascade")
        ver_id = db.upsert_version(lib_id)
        db.add_chunks(
            ver_id,
            lib_id,
            [
                {"content": "cascade test chunk"},
            ],
        )
        db.mark_version_indexed(ver_id, 1, 1)

        db.remove_library("cascade")

        # Chunks should be gone
        results = db.search(query="cascade", library_name="cascade")
        assert results == []
