"""F1: per-sub credential isolation — no cross-user ``os.environ`` bleed.

Regression guard for the multi-user HTTP path where ``_require_credentials``
used to copy a request's per-sub credentials into the process-global
``os.environ`` (and never reset), so a later request for a different ``sub``
read whatever the previous request left behind (cross-user key bleed /
billing + data-isolation breach). The fix resolves each provider key per
call from the request-scoped per-sub bucket via ``api_key_for_model`` and
stops mutating ``os.environ``.

The same isolation applies to the per-sub custom endpoints
(``EMBEDDING_API_BASE`` / ``RERANK_API_BASE`` / ``LLM_API_BASE``): they are
resolved per request via ``api_base_for_task`` so one ``sub``'s gateway URL
never serves another. Reading ``os.getenv`` instead would make the per-sub
relay endpoint a silent no-op in multi-user mode (the endpoint only lives in
the sub bucket, never the shared process env).
"""

from __future__ import annotations

import os

import pytest


def test_require_credentials_does_not_bleed_keys_to_os_environ(monkeypatch, tmp_path):
    monkeypatch.setenv("WET_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CREDENTIAL_SECRET", "s")
    monkeypatch.delenv("JINA_AI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    from wet_mcp.credential_state import set_current_sub, store_for_sub
    from wet_mcp.server import _require_credentials

    store_for_sub("user_a", {"JINA_AI_API_KEY": "key_a"})
    store_for_sub("user_b", {"GEMINI_API_KEY": "key_b"})

    try:
        set_current_sub("user_a")
        assert _require_credentials() is None  # configured -> tool call allowed
        # user_a's key must NOT land in the process-global environment.
        assert os.environ.get("JINA_AI_API_KEY") is None

        set_current_sub("user_b")
        assert _require_credentials() is None
        # user_b must not inherit user_a's key from the previous request,
        # and must not leak its own key into the global env either.
        assert os.environ.get("JINA_AI_API_KEY") is None
        assert os.environ.get("GEMINI_API_KEY") is None
    finally:
        set_current_sub(None)


def test_api_key_for_model_resolves_per_sub(monkeypatch, tmp_path):
    monkeypatch.setenv("WET_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CREDENTIAL_SECRET", "s")
    monkeypatch.delenv("JINA_AI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    from wet_mcp.credential_state import (
        api_key_for_model,
        set_current_sub,
        store_for_sub,
    )

    store_for_sub("user_a", {"JINA_AI_API_KEY": "key_a"})
    store_for_sub("user_b", {"GEMINI_API_KEY": "key_b"})

    try:
        set_current_sub("user_a")
        assert api_key_for_model("jina_ai/jina-embeddings-v5") == "key_a"
        # user_a has no Gemini key -> None (not a bled value from elsewhere).
        assert api_key_for_model("gemini/gemini-3-flash-preview") is None

        set_current_sub("user_b")
        assert api_key_for_model("gemini/gemini-3-flash-preview") == "key_b"
        # no bleed of user_a's Jina key into user_b's request.
        assert api_key_for_model("jina_ai/jina-embeddings-v5") is None
    finally:
        set_current_sub(None)


def test_api_key_for_model_returns_none_for_single_user(monkeypatch, tmp_path):
    """Single-user / stdio (no sub): None so litellm's own env fallback applies.

    The single-user dispatch contract is intentionally unchanged — the cloud
    backends still pass ``api_key=None`` and litellm reads the provider env
    var itself. ``api_key_for_model`` only resolves an explicit key for the
    HTTP multi-user (``sub`` set) path, which is where the bleed lived.
    """
    monkeypatch.setenv("WET_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("OPENAI_API_KEY", "k1")

    from wet_mcp.credential_state import api_key_for_model, set_current_sub

    set_current_sub(None)
    assert api_key_for_model("openai/gpt-4o-mini") is None
    assert api_key_for_model("jina_ai/x") is None


async def test_embedder_forwards_per_sub_api_key(monkeypatch, tmp_path):
    """CloudEmbeddingBackend forwards the request's per-sub key to litellm."""
    monkeypatch.setenv("WET_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CREDENTIAL_SECRET", "s")
    monkeypatch.delenv("JINA_AI_API_KEY", raising=False)

    from wet_mcp.credential_state import set_current_sub, store_for_sub
    from wet_mcp.embedder import CloudEmbeddingBackend

    store_for_sub("user_a", {"JINA_AI_API_KEY": "key_a"})

    captured: dict = {}

    async def fake_aembedding(**kwargs):
        captured.update(kwargs)

        class _R:
            data = [{"index": 0, "embedding": [0.1, 0.2, 0.3]}]

        return _R()

    monkeypatch.setattr("mcp_core.llm.aembedding", fake_aembedding)
    backend = CloudEmbeddingBackend("jina_ai/jina-embeddings-v5", api_key=None)
    try:
        set_current_sub("user_a")
        await backend.embed_single("hello")
        assert captured["api_key"] == "key_a"
    finally:
        set_current_sub(None)


def test_reranker_forwards_per_sub_api_key(monkeypatch, tmp_path):
    """CloudReranker forwards the request's per-sub key to litellm."""
    monkeypatch.setenv("WET_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CREDENTIAL_SECRET", "s")
    monkeypatch.delenv("JINA_AI_API_KEY", raising=False)

    from wet_mcp.credential_state import set_current_sub, store_for_sub
    from wet_mcp.reranker import CloudReranker

    store_for_sub("user_a", {"JINA_AI_API_KEY": "key_a"})

    captured: dict = {}

    def fake_rerank(**kwargs):
        captured.update(kwargs)

        class _R:
            results = [{"index": 0, "relevance_score": 0.9}]

        return _R()

    monkeypatch.setattr("mcp_core.llm.rerank", fake_rerank)
    backend = CloudReranker(model="jina_ai/jina-reranker-v3", api_key=None)
    try:
        set_current_sub("user_a")
        backend.rerank("q", ["doc"], top_n=1)
        assert captured["api_key"] == "key_a"
    finally:
        set_current_sub(None)


async def test_llm_acompletion_forwards_per_sub_api_key(monkeypatch, tmp_path):
    """llm.acompletion forwards the request's per-sub key to litellm."""
    monkeypatch.setenv("WET_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CREDENTIAL_SECRET", "s")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    from wet_mcp.credential_state import set_current_sub, store_for_sub
    from wet_mcp.llm import acompletion

    store_for_sub("user_a", {"GEMINI_API_KEY": "key_a"})

    captured: dict = {}

    async def fake_core_acompletion(**kwargs):
        captured.update(kwargs)
        return object()

    monkeypatch.setattr("mcp_core.llm.acompletion", fake_core_acompletion)
    try:
        set_current_sub("user_a")
        await acompletion(
            model="gemini/gemini-3-flash-preview",
            messages=[{"role": "user", "content": "hi"}],
        )
        assert captured["api_key"] == "key_a"
    finally:
        set_current_sub(None)


# ---------------------------------------------------------------------------
# Per-sub custom endpoint (api_base) — mirror of the api_key isolation above.
# ---------------------------------------------------------------------------


def test_api_base_for_task_resolves_per_sub(monkeypatch, tmp_path):
    """``*_API_BASE`` resolves from the request's per-sub bucket, no bleed."""
    monkeypatch.setenv("WET_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CREDENTIAL_SECRET", "s")
    monkeypatch.delenv("EMBEDDING_API_BASE", raising=False)
    monkeypatch.delenv("RERANK_API_BASE", raising=False)

    from wet_mcp.credential_state import (
        api_base_for_task,
        set_current_sub,
        store_for_sub,
    )

    store_for_sub("user_a", {"EMBEDDING_API_BASE": "https://gw-a/cohere/v2/embed"})
    store_for_sub("user_b", {"EMBEDDING_API_BASE": "https://gw-b/cohere/v2/embed"})

    try:
        set_current_sub("user_a")
        assert api_base_for_task("EMBEDDING_API_BASE") == "https://gw-a/cohere/v2/embed"
        # user_a set no rerank endpoint -> None (not a value bled from elsewhere).
        assert api_base_for_task("RERANK_API_BASE") is None

        set_current_sub("user_b")
        assert api_base_for_task("EMBEDDING_API_BASE") == "https://gw-b/cohere/v2/embed"
        # no bleed of user_a's endpoint into user_b's request.
        assert api_base_for_task("RERANK_API_BASE") is None
    finally:
        set_current_sub(None)


def test_api_base_for_task_env_fallback_single_user(monkeypatch, tmp_path):
    """Single-user / stdio (no sub): read ``os.environ``.

    Unlike provider keys (where ``None`` lets litellm read the env itself),
    litellm does not know wet's ``*_API_BASE`` names, so the single-user path
    must surface the env value here or the custom endpoint would be dropped.
    """
    monkeypatch.setenv("WET_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("EMBEDDING_API_BASE", "https://env-gw/v1")
    monkeypatch.delenv("RERANK_API_BASE", raising=False)

    from wet_mcp.credential_state import api_base_for_task, set_current_sub

    set_current_sub(None)
    assert api_base_for_task("EMBEDDING_API_BASE") == "https://env-gw/v1"
    assert api_base_for_task("RERANK_API_BASE") is None


async def test_embedder_per_sub_api_base_isolation(monkeypatch, tmp_path):
    """Crux of the Y decision: two subs with different EMBEDDING_API_BASE each
    drive their OWN endpoint through the embedder.

    If the embedder read ``os.getenv`` instead of the resolver, both subs would
    share the server-wide env value (or ``None``), making the per-sub relay
    endpoint a silent no-op.
    """
    monkeypatch.setenv("WET_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CREDENTIAL_SECRET", "s")
    monkeypatch.delenv("EMBEDDING_API_BASE", raising=False)

    from wet_mcp.credential_state import set_current_sub, store_for_sub
    from wet_mcp.embedder import CloudEmbeddingBackend

    store_for_sub(
        "user_a", {"JINA_AI_API_KEY": "key_a", "EMBEDDING_API_BASE": "https://gw-a/v1"}
    )
    store_for_sub(
        "user_b", {"JINA_AI_API_KEY": "key_b", "EMBEDDING_API_BASE": "https://gw-b/v1"}
    )

    captured: list[dict] = []

    async def fake_aembedding(**kwargs):
        captured.append(dict(kwargs))

        class _R:
            data = [{"index": 0, "embedding": [0.1]}]

        return _R()

    monkeypatch.setattr("mcp_core.llm.aembedding", fake_aembedding)
    try:
        set_current_sub("user_a")
        await CloudEmbeddingBackend("jina_ai/jina-embeddings-v5").embed_single("x")
        set_current_sub("user_b")
        await CloudEmbeddingBackend("jina_ai/jina-embeddings-v5").embed_single("y")
    finally:
        set_current_sub(None)

    assert captured[0]["api_base"] == "https://gw-a/v1"
    assert captured[0]["api_key"] == "key_a"
    assert captured[1]["api_base"] == "https://gw-b/v1"
    assert captured[1]["api_key"] == "key_b"


def test_reranker_forwards_per_sub_api_base(monkeypatch, tmp_path):
    """CloudReranker forwards the request's per-sub endpoint to litellm."""
    monkeypatch.setenv("WET_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CREDENTIAL_SECRET", "s")
    monkeypatch.delenv("RERANK_API_BASE", raising=False)

    from wet_mcp.credential_state import set_current_sub, store_for_sub
    from wet_mcp.reranker import CloudReranker

    store_for_sub(
        "user_a", {"JINA_AI_API_KEY": "key_a", "RERANK_API_BASE": "https://gw-a/rerank"}
    )

    captured: dict = {}

    def fake_rerank(**kwargs):
        captured.update(kwargs)

        class _R:
            results = [{"index": 0, "relevance_score": 0.9}]

        return _R()

    monkeypatch.setattr("mcp_core.llm.rerank", fake_rerank)
    backend = CloudReranker(model="jina_ai/jina-reranker-v3", api_key=None)
    try:
        set_current_sub("user_a")
        backend.rerank("q", ["doc"], top_n=1)
        assert captured["api_base"] == "https://gw-a/rerank"
        assert captured["api_key"] == "key_a"
    finally:
        set_current_sub(None)


async def test_llm_acompletion_forwards_per_sub_api_base(monkeypatch, tmp_path):
    """llm.acompletion forwards the request's per-sub endpoint to litellm."""
    monkeypatch.setenv("WET_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CREDENTIAL_SECRET", "s")
    monkeypatch.delenv("LLM_API_BASE", raising=False)

    from wet_mcp.credential_state import set_current_sub, store_for_sub
    from wet_mcp.llm import acompletion

    store_for_sub(
        "user_a", {"GEMINI_API_KEY": "key_a", "LLM_API_BASE": "https://gw-a/llm"}
    )

    captured: dict = {}

    async def fake_core_acompletion(**kwargs):
        captured.update(kwargs)
        return object()

    monkeypatch.setattr("mcp_core.llm.acompletion", fake_core_acompletion)
    try:
        set_current_sub("user_a")
        await acompletion(
            model="gemini/gemini-3-flash-preview",
            messages=[{"role": "user", "content": "hi"}],
        )
        assert captured["api_base"] == "https://gw-a/llm"
        assert captured["api_key"] == "key_a"
    finally:
        set_current_sub(None)


async def test_per_sub_api_base_ssrf_rejected_in_multi_user(monkeypatch, tmp_path):
    """A per-sub loopback endpoint is rejected by the SSRF vet in multi-user mode.

    The resolved ``api_base`` flows into the REAL ``mcp_core.llm`` dispatch,
    which vets it via ``vet_api_base`` (``_prep_api_base``) before any network
    call. ``PUBLIC_URL`` set => multi-user => loopback/private blocked
    unconditionally. This proves the per-sub endpoint stays on the vetted path
    rather than bypassing it.
    """
    monkeypatch.setenv("WET_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CREDENTIAL_SECRET", "s")
    monkeypatch.setenv("PUBLIC_URL", "https://wet.example")  # multi-user mode
    monkeypatch.delenv("EMBEDDING_API_BASE", raising=False)

    from mcp_core.http import SSRFBlockedError

    from wet_mcp.credential_state import set_current_sub, store_for_sub
    from wet_mcp.embedder import CloudEmbeddingBackend

    store_for_sub(
        "user_a",
        {"JINA_AI_API_KEY": "key_a", "EMBEDDING_API_BASE": "http://127.0.0.1:9000"},
    )

    try:
        set_current_sub("user_a")
        with pytest.raises(SSRFBlockedError):
            await CloudEmbeddingBackend("jina_ai/jina-embeddings-v5").embed_single("x")
    finally:
        set_current_sub(None)
