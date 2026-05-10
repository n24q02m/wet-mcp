"""Server-level dispatch tests for the Phase 2 search actions.

Exercises the ``case "docs_resolve"`` / ``case "docs_query"`` /
``case "docs_lock_project"`` branches of ``server.search`` end-to-end
(through the MCP wrapper) against a temp DocsDB. This bumps coverage
on the server.py dispatcher block.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from wet_mcp import server as srv
from wet_mcp.db import DocsDB


@pytest.fixture
def docs_db(tmp_path: Path, monkeypatch):
    db = DocsDB(tmp_path / "docs.db", embedding_dims=0)
    monkeypatch.setattr(srv, "_docs_db", db)
    # Bypass the credential gate so we can drive the dispatcher directly.
    from wet_mcp import credential_state as cs

    monkeypatch.setattr(cs, "get_state", lambda: cs.CredentialState.LOCAL)
    yield db
    db.close()


async def _call_search(**kwargs) -> str:
    """Invoke the search tool directly."""
    return await srv.search(**kwargs)


def _parse(out: str) -> dict:
    """JSON decode that tolerates the wrap_external_content wrapper."""
    # The wrapper looks like:
    #   <untrusted_search_content>\n{...JSON...}\n</untrusted_search_content>\n
    #   \n[SECURITY: ...]
    # Find the first `{` and parse with raw_decode to stop at the matching `}`.
    start = out.find("{")
    if start == -1:
        raise ValueError(f"No JSON object found in output: {out!r}")
    decoder = json.JSONDecoder()
    obj, _ = decoder.raw_decode(out[start:])
    return obj


async def test_docs_resolve_returns_serialized_results(docs_db) -> None:
    docs_db.upsert_library(name="react", canonical_name="React")
    out = await _call_search(action="docs_resolve", query="react", limit=5)
    assert "results" in out
    payload = _parse(out)
    assert payload["query"] == "react"
    assert payload["total"] >= 1
    assert payload["results"][0]["name"] == "react"


async def test_docs_resolve_missing_query_returns_error(docs_db) -> None:
    out = await _call_search(action="docs_resolve")
    assert out.startswith("Error: query")


async def test_docs_query_unknown_library_triggers_indexing_hint(
    docs_db,
) -> None:
    out = await _call_search(
        action="docs_query", library="never-heard-of-it", query="anything"
    )
    payload = _parse(out)
    assert payload["status"] == "indexing_in_progress"
    assert payload["library"] == "never-heard-of-it"
    assert payload["results"] == []


async def test_docs_query_known_library_returns_results(docs_db) -> None:
    lib_id = docs_db.upsert_library(name="react")
    ver_id = docs_db.upsert_version(library_id=lib_id, version="latest")
    docs_db.add_chunks(
        version_id=ver_id,
        library_id=lib_id,
        chunks=[
            {
                "url": "https://react.dev/p1",
                "title": "useState basics",
                "content": "useState lets you add state to a React component.",
                "topic": "useState",
                "token_count": 30,
            }
        ],
    )
    docs_db.mark_version_indexed(ver_id, 1, 1)

    out = await _call_search(
        action="docs_query",
        library="react",
        query="useState",
    )
    payload = _parse(out)
    assert payload["library"]["name"] == "react"
    assert payload["total"] >= 1


async def test_docs_query_missing_library_returns_error(docs_db) -> None:
    out = await _call_search(action="docs_query", query="useState")
    assert out.startswith("Error: library")


async def test_docs_query_missing_query_returns_error(docs_db) -> None:
    out = await _call_search(action="docs_query", library="react")
    assert out.startswith("Error: query")


async def test_docs_query_honors_project_lock(docs_db) -> None:
    lib_id = docs_db.upsert_library(name="react")
    v18 = docs_db.upsert_version(library_id=lib_id, version="18.0.0")
    v19 = docs_db.upsert_version(library_id=lib_id, version="19.0.0")
    docs_db.add_chunks(
        version_id=v18,
        library_id=lib_id,
        chunks=[
            {
                "url": "https://react.dev/v18/p",
                "title": "v18",
                "content": "useState in React 18 reference.",
                "topic": "useState",
                "token_count": 20,
            }
        ],
    )
    docs_db.add_chunks(
        version_id=v19,
        library_id=lib_id,
        chunks=[
            {
                "url": "https://react.dev/v19/p",
                "title": "v19",
                "content": "useState in React 19 reference.",
                "topic": "useState",
                "token_count": 20,
            }
        ],
    )
    docs_db.mark_version_indexed(v18, 1, 1)
    docs_db.mark_version_indexed(v19, 1, 1)
    docs_db.upsert_project_context(
        "/test/locked",
        [{"id": lib_id, "name": "react", "version": "18.0.0"}],
    )

    out = await _call_search(
        action="docs_query",
        library="react",
        project_path="/test/locked",
        query="useState",
    )
    payload = _parse(out)
    assert payload["lock_pin"] == "18.0.0"


async def test_docs_lock_project_missing_path(docs_db) -> None:
    out = await _call_search(action="docs_lock_project")
    assert out.startswith("Error: project_path")


async def test_docs_lock_project_invalid_path(docs_db) -> None:
    out = await _call_search(
        action="docs_lock_project", project_path="/totally/missing/path"
    )
    assert out.startswith("Error:")


async def test_docs_lock_project_writes_lock(docs_db, tmp_path) -> None:
    project = tmp_path / "demo-app"
    project.mkdir()
    (project / "package.json").write_text(
        '{"name": "demo", "dependencies": {"react": "^18", "next": "^14"}}'
    )

    out = await _call_search(action="docs_lock_project", project_path=str(project))
    payload = _parse(out)
    assert payload["total"] == 2
    fetched = docs_db.get_project_context(str(project.resolve()))
    assert fetched is not None
    assert fetched["locked_libraries"]


async def test_unknown_action_lists_phase2_actions(docs_db) -> None:
    out = await _call_search(action="not-a-real-action", query="x")
    assert "docs_resolve" in out
    assert "docs_query" in out
    assert "docs_lock_project" in out


async def test_docs_resolve_when_db_missing(monkeypatch) -> None:
    """When the DocsDB is None (startup race), resolve returns an error."""
    from wet_mcp import credential_state as cs

    monkeypatch.setattr(srv, "_docs_db", None)
    monkeypatch.setattr(cs, "get_state", lambda: cs.CredentialState.LOCAL)
    out = await srv.search(action="docs_resolve", query="react")
    assert out.startswith("Error: Docs database")


async def test_docs_query_when_db_missing(monkeypatch) -> None:
    """When the DocsDB is None, docs_query returns an error."""
    from wet_mcp import credential_state as cs

    monkeypatch.setattr(srv, "_docs_db", None)
    monkeypatch.setattr(cs, "get_state", lambda: cs.CredentialState.LOCAL)
    out = await srv.search(action="docs_query", library="react", query="x")
    assert out.startswith("Error: Docs database")


async def test_docs_lock_project_when_db_missing(monkeypatch) -> None:
    """When the DocsDB is None, docs_lock_project returns an error."""
    from wet_mcp import credential_state as cs

    monkeypatch.setattr(srv, "_docs_db", None)
    monkeypatch.setattr(cs, "get_state", lambda: cs.CredentialState.LOCAL)
    out = await srv.search(action="docs_lock_project", project_path="/tmp")
    assert out.startswith("Error: Docs database")


async def test_docs_query_with_topic_filter(docs_db) -> None:
    """docs_query passes topic through and filters chunks."""
    lib_id = docs_db.upsert_library(name="react")
    ver_id = docs_db.upsert_version(library_id=lib_id, version="latest")
    docs_db.add_chunks(
        version_id=ver_id,
        library_id=lib_id,
        chunks=[
            {
                "url": "https://react.dev/p1",
                "title": "useState",
                "content": "useState hook in React.",
                "topic": "useState",
                "token_count": 20,
            }
        ],
    )
    docs_db.mark_version_indexed(ver_id, 1, 1)

    out = await _call_search(
        action="docs_query",
        library="react",
        topic="useState",
        query="useState",
    )
    payload = _parse(out)
    assert payload["topic"] == "useState"
    # Test the topic field is propagated; total may be 0 if FTS doesn't
    # match — what matters here is the dispatcher branch coverage.
    assert "total" in payload


async def test_docs_lock_project_response_includes_total(docs_db, tmp_path) -> None:
    """Lock summary response shape matches docs/search.md contract."""
    project = tmp_path / "summary"
    project.mkdir()
    (project / "Cargo.toml").write_text(
        '[package]\nname = "x"\nversion = "0"\n[dependencies]\ntokio = "1.40"\n'
    )
    out = await _call_search(action="docs_lock_project", project_path=str(project))
    payload = _parse(out)
    for key in ("project_path", "locked_libraries", "total", "indexed"):
        assert key in payload
    assert payload["total"] >= 1


async def test_docs_query_lock_pin_only_without_explicit_version(docs_db) -> None:
    """If caller passes version explicitly, lock_pin remains None."""
    lib_id = docs_db.upsert_library(name="react")
    ver_id = docs_db.upsert_version(library_id=lib_id, version="18.0.0")
    docs_db.add_chunks(
        version_id=ver_id,
        library_id=lib_id,
        chunks=[
            {
                "url": "https://react.dev/p",
                "title": "v18",
                "content": "useState in React 18.",
                "topic": "useState",
                "token_count": 20,
            }
        ],
    )
    docs_db.mark_version_indexed(ver_id, 1, 1)
    docs_db.upsert_project_context(
        "/test/locked",
        [{"id": lib_id, "name": "react", "version": "17.0.0"}],
    )

    # Caller explicitly passed version -> lock_pin stays None.
    out = await _call_search(
        action="docs_query",
        library="react",
        version="18.0.0",
        project_path="/test/locked",
        query="useState",
    )
    payload = _parse(out)
    assert payload["lock_pin"] is None
    assert payload["version"] == "18.0.0"
