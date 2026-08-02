"""The Tier 1 ingest script and the server must agree on embedding identity.

``DocsDB`` stamps ``(embedding_model, embedding_dims)`` into ``store_meta`` on
first open and refuses to reopen a store stamped with a different identity
(``EmbeddingModelMismatch``). That guard is correct. What was wrong is that
``scripts/build_tier1_index.py`` opened the SAME ``~/.wet-mcp/docs.db`` with a
hand-written identity of its own -- ``DocsDB(path, embedding_dims=0)``, no
model id -- which no server ever produces. The two callers therefore stamped
two different identities into one file, and whichever ran second was refused:

* server first, script second -- eager ingest is impossible on any machine
  that has ever started the server.
* script first, server second -- the weekly ``refresh-tier1`` job exits 0 on a
  clean runner and leaves behind a ``docs.db`` no server can open. Nothing in
  CI starts a server afterwards, so the job reports success.

These tests pin both directions, and pin the CI-runner case specifically: with
no provider key in the environment the stamped dims must still be the server's
768, never 0.
"""

from __future__ import annotations

import importlib.util
import pathlib
import sqlite3

import pytest

from wet_mcp import server
from wet_mcp.config import settings
from wet_mcp.db import EmbeddingModelMismatch

_SCRIPT = (
    pathlib.Path(__file__).resolve().parent.parent / "scripts" / "build_tier1_index.py"
)
_spec = importlib.util.spec_from_file_location("build_tier1_index", _SCRIPT)
assert _spec is not None and _spec.loader is not None
build_tier1_index = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(build_tier1_index)

# Every provider key the curated embedding chain can be gated on. Cleared so a
# developer shell that exports one does not turn a clean-runner test into a
# cloud-identity test.
_PROVIDER_KEYS = (
    "JINA_AI_API_KEY",
    "GEMINI_API_KEY",
    "GOOGLE_API_KEY",
    "OPENAI_API_KEY",
    "COHERE_API_KEY",
)


@pytest.fixture
def clean_runner_env(monkeypatch):
    """Reproduce a clean CI runner: no provider keys, no rebuild escape hatch.

    ``REINDEX_ON_MODEL_CHANGE`` is cleared on both the env and the settings
    singleton: with it set the guard rebuilds instead of raising, which is
    exactly how a developer shell that exports it hides this bug.
    """
    for key in _PROVIDER_KEYS:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.delenv("EMBEDDING_MODELS", raising=False)
    monkeypatch.delenv("EMBEDDING_DIMS", raising=False)
    monkeypatch.delenv("REINDEX_ON_MODEL_CHANGE", raising=False)
    monkeypatch.delenv("DOCS_DB_BACKEND", raising=False)
    monkeypatch.setattr(settings, "embedding_models", "")
    monkeypatch.setattr(settings, "embedding_model", "")
    monkeypatch.setattr(settings, "embedding_backend", "")
    monkeypatch.setattr(settings, "embedding_dims", 0)
    monkeypatch.setattr(settings, "reindex_on_model_change", False)
    monkeypatch.setattr(settings, "docs_db_backend", "sqlite")


@pytest.fixture
def cloud_embedding_env(clean_runner_env, monkeypatch):
    """A machine configured the way the README's manual config example is."""
    monkeypatch.setenv("JINA_AI_API_KEY", "placeholder-not-a-real-key")
    monkeypatch.setattr(
        settings, "embedding_models", "jina_ai/jina-embeddings-v5-text-small"
    )


def _stamp(db_path: pathlib.Path) -> dict[str, str]:
    """Read the embedding identity recorded in ``store_meta``."""
    conn = sqlite3.connect(str(db_path))
    try:
        return dict(
            conn.execute(
                "SELECT key, value FROM store_meta "
                "WHERE key IN ('embedding_model', 'embedding_dims')"
            ).fetchall()
        )
    finally:
        conn.close()


def _open_as_server(db_path: pathlib.Path, monkeypatch):
    """Open ``db_path`` through the server's own construction path.

    Goes through ``settings.get_db_path()`` rather than an argument, so the
    test exercises the resolution a running server actually uses.
    """
    monkeypatch.setattr(settings, "docs_db_path", str(db_path))
    return server.make_docs_db()


def test_script_stamped_store_opens_with_server_construction(
    tmp_path, monkeypatch, clean_runner_env
):
    """Direction 2: the weekly job's store must be openable by a server.

    This is the CI case. No provider key is present, which is precisely when
    the script used to stamp dims=0.
    """
    db_path = tmp_path / "docs.db"

    build_tier1_index.open_docs_db(db_path).close()
    script_stamp = _stamp(db_path)

    # The stamp has to be a real identity, not the "no model, no dims"
    # placeholder: dims=0 disables sqlite-vec entirely, so a store carrying it
    # could never hold the vectors the server expects to find there.
    assert script_stamp.get("embedding_dims") != "0", (
        f"script stamped a dims=0 identity no server produces: {script_stamp}"
    )

    _open_as_server(db_path, monkeypatch).close()
    assert _stamp(db_path) == script_stamp, (
        "opening as the server changed the stamp, so the two callers still "
        "disagree about identity"
    )


def test_script_opens_store_stamped_by_server(
    tmp_path, monkeypatch, cloud_embedding_env
):
    """Direction 1: eager ingest on a machine that has run the server.

    The reported crash: a real ``~/.wet-mcp/docs.db`` stamped
    ``jina_ai/jina-embeddings-v5-text-small`` dims=768 by the server, which the
    script then refused to open.
    """
    db_path = tmp_path / "docs.db"

    _open_as_server(db_path, monkeypatch).close()
    server_stamp = _stamp(db_path)
    assert server_stamp == {
        "embedding_dims": "768",
        "embedding_model": "jina_ai/jina-embeddings-v5-text-small",
    }, server_stamp

    build_tier1_index.open_docs_db(db_path).close()
    assert _stamp(db_path) == server_stamp


def test_script_and_server_agree_without_any_provider_key(
    tmp_path, monkeypatch, clean_runner_env
):
    """Both orders agree on a clean runner, and neither stamps dims=0.

    Pins the answer to "what does a keyless runner resolve to": the local ONNX
    identity at the server's default 768 dims, not ``unavailable``/0.
    """
    script_first = tmp_path / "script_first.db"
    build_tier1_index.open_docs_db(script_first).close()

    server_first = tmp_path / "server_first.db"
    _open_as_server(server_first, monkeypatch).close()

    assert _stamp(script_first) == _stamp(server_first)
    assert _stamp(script_first)["embedding_dims"] == "768"


def test_script_refuses_cf_d1_instead_of_writing_the_wrong_store(
    tmp_path, monkeypatch, clean_runner_env
):
    """``DOCS_DB_BACKEND=cf-d1`` must fail loudly, not ingest somewhere else.

    The script is SQLite-shaped end to end: ``--db-path``,
    ``run_migrations_on_startup(args.db_path)``, and a metrics file written
    next to the database. Under cf-d1 the store lives in D1 + Vectorize and
    the path means nothing, so honouring the flag silently would ingest into a
    different store than the operator named.
    """
    monkeypatch.setenv("DOCS_DB_BACKEND", "cf-d1")

    with pytest.raises(RuntimeError, match="cf-d1"):
        build_tier1_index.open_docs_db(tmp_path / "docs.db")


def test_ingest_works_without_an_embedder_available(
    tmp_path, monkeypatch, clean_runner_env
):
    """A keyless runner must still be able to write chunks.

    The fix raises the stamped dims from 0 to 768, which turns on the
    sqlite-vec table. CI has no provider key and downloads no local model, so
    if ``add_chunks`` needed an embedder once dims > 0 the fix would trade a
    corrupt store for a broken weekly job.
    """
    db_path = tmp_path / "docs.db"
    db = build_tier1_index.open_docs_db(db_path)
    try:
        lib_id = db.upsert_library(name="requests", canonical_name="requests")
        ver_id = db.upsert_version(library_id=lib_id, version="latest")
        # Exactly how ingest_tier2 calls it: no ``embeddings`` argument.
        written = db.add_chunks(
            version_id=ver_id,
            library_id=lib_id,
            chunks=[
                {
                    "url": "https://example.com/doc",
                    "title": "Doc",
                    "content": "some documentation text",
                    "heading_path": "",
                    "chunk_index": 0,
                }
            ],
        )
    finally:
        db.close()

    assert written == 1
    conn = sqlite3.connect(str(db_path))
    try:
        assert conn.execute("SELECT count(*) FROM doc_chunks").fetchone()[0] == 1
    finally:
        conn.close()


def test_guard_still_fires_on_a_genuine_model_change(
    tmp_path, monkeypatch, clean_runner_env
):
    """Positive control: the fix must not have defanged the guard.

    Every other test here asserts something opens. Without this one they would
    also pass if the guard had been disabled, the exception swallowed, or
    ``REINDEX_ON_MODEL_CHANGE`` switched on.
    """
    db_path = tmp_path / "docs.db"
    build_tier1_index.open_docs_db(db_path).close()

    monkeypatch.setenv("JINA_AI_API_KEY", "placeholder-not-a-real-key")
    monkeypatch.setattr(
        settings, "embedding_models", "jina_ai/jina-embeddings-v5-text-small"
    )
    with pytest.raises(EmbeddingModelMismatch):
        build_tier1_index.open_docs_db(db_path)
