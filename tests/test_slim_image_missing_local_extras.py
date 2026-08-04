"""The local ONNX leg must be resolved from the IMAGE, not only from a flag.

The http-slim build uninstalls ``qwen3-embed`` and ``onnxruntime`` (see
``Dockerfile``), so on that image the local embed/rerank leg does not exist --
whatever the configuration says. Every resolver in the codebase decided the
question from ``DISABLE_LOCAL_EMBED`` / ``DISABLE_LOCAL_RERANK`` alone, which
makes a slim deployment correct only for as long as somebody remembers to set
those vars. Forget one, or run the slim image outside the Cloudflare worker
that supplies them, and the first index attempt dies inside the lazy import in
``Qwen3EmbedBackend._get_model``. Live prod D1 recorded exactly that (#1630)::

    fastapi:python  pending  0 chunks  failed
        ModuleNotFoundError: No module named 'qwen3_embed'

-- a hard failure with zero chunks, where the same request had a perfectly good
keyword-only degrade available to it.

These tests pin the fix at four levels: the per-request resolvers, the reason
string a caller is told, the durable record the background indexer leaves in
``versions.index_error``, and the startup path that used to install a backend
it had already proved could not load.

Both ``qwen3_embed`` and ``onnxruntime`` ARE installed in the dev venv, so the
slim container cannot be reproduced by simply not having them. The
``slim_image`` fixture simulates both packages on two channels at once:
``find_spec`` answers "absent" (what the fix is supposed to consult) and
``__import__`` raises (what the old code hit). Recording every attempted import
is what lets these tests assert the local leg was never entered, rather than
merely that the return value looked right.
"""

from __future__ import annotations

import builtins
import importlib.util
from unittest.mock import AsyncMock

import pytest

from wet_mcp import server
from wet_mcp.credential_state import CLOUD_KEYS, set_current_sub, store_for_sub
from wet_mcp.db import INDEX_STATE_DONE, INDEX_STATE_RUNNING, DocsDB

# Captured at collection time, BEFORE conftest's autouse ``_stub_phase2_lifespan_hooks``
# replaces both factories with MagicMocks that report a healthy backend and never
# touch the module singleton. Under that stub the startup tests below pass on
# unfixed code, asserting nothing. Its docstring says as much: "Tests that
# exercise these init factories patch the same targets themselves."
from wet_mcp.embedder import init_backend as _REAL_INIT_BACKEND
from wet_mcp.reranker import init_reranker as _REAL_INIT_RERANKER

DOCS_URL = "https://example.test/alpha"


@pytest.fixture(autouse=True)
def _isolate(monkeypatch, tmp_path):
    """No provider keys, no chains, and both disable-local flags OFF.

    The flags being off is the whole point: this module covers the deployment
    that never set them and is nonetheless running an image without the local
    extras.
    """
    monkeypatch.setenv("WET_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CREDENTIAL_SECRET", "s")
    set_current_sub(None)
    for k in (*CLOUD_KEYS, "ANTHROPIC_API_KEY", "GOOGLE_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    for k in ("EMBEDDING_MODELS", "RERANK_MODELS", "LLM_MODELS"):
        monkeypatch.delenv(k, raising=False)

    from wet_mcp import embedder, reranker
    from wet_mcp.config import settings

    monkeypatch.setattr(settings, "disable_local_embed", False)
    monkeypatch.setattr(settings, "disable_local_rerank", False)
    monkeypatch.setattr(settings, "embedding_models", "")
    monkeypatch.setattr(settings, "rerank_models", "")
    # Process-wide singletons; a leftover from another module would make these
    # assertions pass or fail for the wrong reason.
    monkeypatch.setattr(embedder, "_shared_local_backend", None)
    monkeypatch.setattr(reranker, "_shared_local_backend", None)
    monkeypatch.setattr(embedder, "_backend", None)
    monkeypatch.setattr(reranker, "_backend", None)
    yield
    set_current_sub(None)


@pytest.fixture
def slim_image(monkeypatch):
    """Make both local ONNX packages absent as the slim build leaves them.

    Returns the list of import names the code under test asked for; an empty
    list is the assertion that the local leg was never entered at all.
    """
    real_import = builtins.__import__
    real_find_spec = importlib.util.find_spec
    attempted: list[str] = []
    missing = ("qwen3_embed", "onnxruntime")

    def _guarded_import(name, *args, **kwargs):
        if any(
            name == package or name.startswith(f"{package}.") for package in missing
        ):
            attempted.append(name)
            raise ModuleNotFoundError(f"No module named '{name}'")
        return real_import(name, *args, **kwargs)

    def _guarded_find_spec(name, *args, **kwargs):
        if any(
            name == package or name.startswith(f"{package}.") for package in missing
        ):
            return None
        return real_find_spec(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _guarded_import)
    monkeypatch.setattr(importlib.util, "find_spec", _guarded_find_spec)
    return attempted


# ---------------------------------------------------------------------------
# Per-request resolution
# ---------------------------------------------------------------------------


class TestEmbedResolutionOnASlimImage:
    def test_absent_local_extras_resolve_to_none_without_any_flag(self, slim_image):
        """The flag is unset; the package is gone. That is still 'unavailable'."""
        from wet_mcp.embedder import resolve_embed_backend_for_request

        store_for_sub("user_a", {"GITHUB_TOKEN": "ghp_x"})
        set_current_sub("user_a")

        assert resolve_embed_backend_for_request() is None
        assert slim_image == [], f"local ONNX leg was entered: {slim_image}"

    async def test_index_batch_degrades_instead_of_raising(self, slim_image):
        """``_embed_batch`` is what the background indexer calls.

        On main this raises ``ModuleNotFoundError`` straight through
        ``_embed_batch``'s permanent-error branch, which is how the failure
        reached D1 as the version's ``index_error``.
        """
        store_for_sub("user_a", {"GITHUB_TOKEN": "ghp_x"})
        set_current_sub("user_a")

        assert await server._embed_batch(["a", "b"]) is None
        assert slim_image == [], f"local ONNX leg was entered: {slim_image}"

    async def test_query_embed_degrades_instead_of_raising(self, slim_image):
        store_for_sub("user_a", {"GITHUB_TOKEN": "ghp_x"})
        set_current_sub("user_a")

        assert await server._embed("hello", is_query=True) is None
        assert slim_image == [], f"local ONNX leg was entered: {slim_image}"

    def test_reason_names_the_missing_package_not_a_flag_nobody_set(self, slim_image):
        """A reason must be true. ``DISABLE_LOCAL_EMBED`` is not set here.

        Telling an operator to look at a flag they never touched sends them
        after the wrong thing; the actionable fact is that the image has no
        local extras, so the deployment needs a cloud chain.
        """
        from wet_mcp.embedder import embedding_unavailable_reason

        store_for_sub("user_a", {"GITHUB_TOKEN": "ghp_x"})
        set_current_sub("user_a")

        reason = embedding_unavailable_reason()
        assert reason is not None
        assert "qwen3-embed" in reason
        assert "onnxruntime" in reason
        # Named as a property of the build, so the reader looks for a cloud
        # chain rather than a flag to unset.
        assert "slim" in reason
        assert "DISABLE_LOCAL_EMBED" not in reason

    def test_reason_still_names_the_flag_when_the_flag_is_what_did_it(
        self, monkeypatch
    ):
        """Control for the branch above: the flag wording must not be lost."""
        from wet_mcp.config import settings
        from wet_mcp.embedder import embedding_unavailable_reason

        monkeypatch.setattr(settings, "disable_local_embed", True)
        store_for_sub("user_a", {"GITHUB_TOKEN": "ghp_x"})
        set_current_sub("user_a")

        reason = embedding_unavailable_reason()
        assert reason is not None
        assert "DISABLE_LOCAL_EMBED" in reason
        assert "qwen3-embed" not in reason

    def test_installed_local_extras_are_still_used(self):
        """No regression: a full image with the flag off keeps its local leg."""
        from wet_mcp import embedder
        from wet_mcp.embedder import Qwen3EmbedBackend

        store_for_sub("user_a", {"GITHUB_TOKEN": "ghp_x"})
        set_current_sub("user_a")

        backend = embedder.resolve_embed_backend_for_request()
        assert isinstance(backend, Qwen3EmbedBackend)
        assert backend is embedder.resolve_embed_backend_for_request()


class TestRerankResolutionOnASlimImage:
    def test_absent_local_extras_resolve_to_none_without_any_flag(self, slim_image):
        from wet_mcp.reranker import resolve_rerank_backend_for_request

        store_for_sub("user_a", {"GITHUB_TOKEN": "ghp_x"})
        set_current_sub("user_a")

        assert resolve_rerank_backend_for_request() is None
        assert slim_image == [], f"local ONNX leg was entered: {slim_image}"

    async def test_rerank_returns_unranked_order_touching_nothing(self, slim_image):
        """``Qwen3Reranker.rerank`` swallows its own load failure and returns
        ``[]``, so the broken leg is invisible in the result. The import list is
        the only thing that can tell "skipped" from "failed quietly"."""
        store_for_sub("user_a", {"GITHUB_TOKEN": "ghp_x"})
        set_current_sub("user_a")

        results = [{"content": "doc-a"}, {"content": "doc-b"}]
        assert await server._rerank_results("q", results, top_n=1) == [
            {"content": "doc-a"}
        ]
        assert slim_image == [], f"local ONNX leg was entered: {slim_image}"

    def test_installed_local_extras_are_still_used(self):
        from wet_mcp import reranker
        from wet_mcp.reranker import Qwen3Reranker

        store_for_sub("user_a", {"GITHUB_TOKEN": "ghp_x"})
        set_current_sub("user_a")

        assert isinstance(reranker.resolve_rerank_backend_for_request(), Qwen3Reranker)


# ---------------------------------------------------------------------------
# The durable record -- the D1 row from the issue
# ---------------------------------------------------------------------------


@pytest.fixture
def docs_db(tmp_path, monkeypatch):
    """A real store, so the outcome is asserted where an operator reads it."""
    db = DocsDB(tmp_path / "docs.db", embedding_dims=0)
    monkeypatch.setattr(server, "_docs_db", db)
    yield db
    db.close()


@pytest.fixture
def no_searxng(monkeypatch):
    """Keep the indexer's alternate-source leg off the network."""
    monkeypatch.setattr(
        server,
        "ensure_searxng",
        AsyncMock(side_effect=RuntimeError("searxng disabled in tests")),
    )


def _fresh_version(db: DocsDB):
    """A never-indexed version, as ``fastapi:python`` was in prod."""
    lib_id = db.upsert_library(name="alpha", docs_url=DOCS_URL)
    ver_id = db.upsert_version(library_id=lib_id, version="latest", docs_url=DOCS_URL)
    db.set_index_state(ver_id, INDEX_STATE_RUNNING)
    return lib_id, ver_id


def _chunks(n: int):
    return [
        {
            "url": f"{DOCS_URL}/page",
            "title": "T",
            "chunk_index": i,
            "content": f"chunk body number {i}",
            "heading_path": "T",
        }
        for i in range(n)
    ]


class TestBackgroundIndexerOnASlimImage:
    async def test_it_stores_keyword_only_chunks_and_records_why(
        self, docs_db, no_searxng, slim_image, monkeypatch
    ):
        """The exact prod row, inverted.

        Before: ``state=failed``, ``error='ModuleNotFoundError: No module named
        'qwen3_embed''``, ``chunk_count=0`` -- the library unservable forever.
        After: the chunks land keyword-searchable and the version says, where
        ``config(action="status")`` and D1 both show it, that it holds no
        vectors and why. Storing them silently would trade a loud failure for a
        quiet one, which is the outcome this test exists to forbid.
        """
        lib_id, ver_id = _fresh_version(docs_db)
        monkeypatch.setattr(
            server, "_fetch_and_chunk_docs", AsyncMock(return_value=(_chunks(2), 3))
        )
        store_for_sub("user_a", {"GITHUB_TOKEN": "ghp_x"})
        set_current_sub("user_a")

        await server._background_index_and_search(
            library="alpha",
            lib_key="alpha",
            language=None,
            docs_url=DOCS_URL,
            repo_url="",
            query="how to install",
            version=None,
            lib_id=lib_id,
            ver_id=ver_id,
        )

        state = docs_db.get_index_state(ver_id)
        assert state is not None, "the attempt left no record at all"
        assert state["state"] == INDEX_STATE_DONE
        assert state["chunk_count"] == 2, "the keyword-searchable chunks were lost"
        assert docs_db.search("chunk body", library_name="alpha")

        error = state["error"] or ""
        assert "ModuleNotFoundError" not in error
        assert "qwen3-embed" in error
        assert "keyword" in error.lower(), (
            "the record must say the version holds no vectors, not just that "
            f"something was off: {error!r}"
        )
        assert slim_image == [], f"local ONNX leg was entered: {slim_image}"

    async def test_a_fully_embedded_index_records_no_complaint(
        self, docs_db, no_searxng, monkeypatch
    ):
        """Control: the happy path must not grow a spurious error string."""
        from wet_mcp import embedder

        lib_id, ver_id = _fresh_version(docs_db)
        monkeypatch.setattr(
            server, "_fetch_and_chunk_docs", AsyncMock(return_value=(_chunks(2), 3))
        )
        # A resolvable backend, or the indexer takes the keyword-only branch
        # before it ever calls _embed_batch.
        embed_backend = AsyncMock()
        embed_backend.embed_texts = AsyncMock(return_value=[[0.1] * 4] * 2)
        monkeypatch.setattr(embedder, "_backend", embed_backend)

        await server._background_index_and_search(
            library="alpha",
            lib_key="alpha",
            language=None,
            docs_url=DOCS_URL,
            repo_url="",
            query="how to install",
            version=None,
            lib_id=lib_id,
            ver_id=ver_id,
        )

        state = docs_db.get_index_state(ver_id)
        assert state["state"] == INDEX_STATE_DONE
        assert state["error"] is None


# ---------------------------------------------------------------------------
# Startup
# ---------------------------------------------------------------------------


@pytest.fixture
def real_backend_factories(monkeypatch):
    """Undo conftest's blanket stubbing of the two init factories.

    Without this the code under test never runs at all.
    """
    from wet_mcp import embedder, reranker

    monkeypatch.setattr(embedder, "init_backend", _REAL_INIT_BACKEND)
    monkeypatch.setattr(reranker, "init_reranker", _REAL_INIT_RERANKER)


class TestStartupNeverInstallsABackendItCannotLoad:
    async def test_local_backend_is_not_installed_when_the_package_is_absent(
        self, slim_image, real_backend_factories, monkeypatch
    ):
        """``init_backend`` assigns the singleton BEFORE anything validates it.

        With the extras gone, ``check_available()`` fails, the failure is
        logged -- and the unusable backend stays installed as the process
        singleton, so every later request resolves to an object whose first use
        raises. It also defeats the ``is None`` guard in the indexer, which is
        the one place written to produce a loud, informative degrade.
        """
        from wet_mcp import credential_state, embedder
        from wet_mcp.credential_state import CredentialState

        monkeypatch.setattr(
            credential_state, "get_state", lambda: CredentialState.LOCAL
        )

        await server._init_embedding_backend("local")

        assert embedder.get_backend() is None
        assert slim_image == [], f"local ONNX leg was entered: {slim_image}"

    async def test_local_reranker_is_not_installed_when_the_package_is_absent(
        self, slim_image, real_backend_factories, monkeypatch
    ):
        from wet_mcp import credential_state, reranker
        from wet_mcp.credential_state import CredentialState

        monkeypatch.setattr(
            credential_state, "get_state", lambda: CredentialState.LOCAL
        )

        await server._init_reranker_backend("local")

        assert reranker.get_reranker() is None
        assert slim_image == [], f"local ONNX leg was entered: {slim_image}"
