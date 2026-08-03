"""End-to-end CF verification against deterministic fakes. Covers the credential
KV roundtrip, encrypted token storage, D1+Vectorize hybrid search, Tavily search,
outbound latency, and JWT-sub persistence across container recreate (the
deterministic signing key shipped in mcp-core 1.18.0b5, pinned here)."""

from pathlib import Path

from conftest_cf import FakeD1Http, FakeVectorizeHttp
from mcp_core.storage.backends import CfKvBackend
from mcp_core.storage.d1 import D1Backend
from mcp_core.storage.vectorize import VectorizeBackend

from wet_mcp.db_cf import DocsDBCfBackend

DDL = Path("migrations/0001_init_wet.sql").read_text(encoding="utf-8")


def _cf_db(d1, vec):
    """Build a DocsDBCfBackend over injected fakes (mirrors test_db_cf._backend)."""
    return DocsDBCfBackend(d1, vec)


def test_credential_save_to_kv_roundtrip(monkeypatch, fake_kv_http):
    monkeypatch.setenv("CREDENTIAL_SECRET", "k")
    from mcp_core.storage.per_plugin_store import PerPluginStore

    backend = CfKvBackend("http://kv.internal", http=fake_kv_http)
    PerPluginStore("wet", "user1", backend=backend).save({"JINA_AI_API_KEY": "key1"})
    assert any("subs/user1/config" in k for k in fake_kv_http.store)
    assert PerPluginStore("wet", "user1", backend=backend).load() == {
        "JINA_AI_API_KEY": "key1"
    }


def test_token_save_to_kv_encrypted(monkeypatch, fake_kv_http):
    monkeypatch.setenv("CREDENTIAL_SECRET", "k")
    from wet_mcp.token_store import load_token_for_sub, save_token_for_sub

    backend = CfKvBackend("http://kv.internal", http=fake_kv_http)
    save_token_for_sub("user1", "google_drive", {"access_token": "t"}, backend=backend)
    assert any("subs/user1/tokens/google_drive" in k for k in fake_kv_http.store)
    assert load_token_for_sub("user1", "google_drive", backend=backend) == {
        "access_token": "t"
    }


def test_search_with_cf_db_eventual_consistency():
    d1 = D1Backend("http://d1.internal", http=FakeD1Http(DDL))
    vec = VectorizeBackend(
        "http://vectorize.internal", idx="wet", http=FakeVectorizeHttp(ready_after=2)
    )
    db = _cf_db(d1, vec)
    db.upsert_library("alpha", docs_url="https://a")
    lib = db.get_library("alpha")
    # upsert_version returns the id directly. get_best_version means "best
    # INDEXED version", and this row does not reach status='indexed' until
    # mark_version_indexed runs, so it is the wrong way to fetch a fresh row.
    ver_id = db.upsert_version(lib["id"], "1.0")
    db.add_chunks(
        ver_id,
        lib["id"],
        [
            {
                "id": "c1",
                "url": "https://a/p",
                "title": "T",
                "chunk_index": 0,
                "content": "vector search cosine",
                "heading_path": "H",
            }
        ],
        embeddings=[[1.0, 0.0] + [0.0] * 766],
    )
    out = db.search("vector search", limit=5, query_embedding=[1.0, 0.0] + [0.0] * 766)
    assert out and out[0]["url"] == "https://a/p"


async def test_tavily_fallback(monkeypatch):
    import unittest.mock

    monkeypatch.setenv("SEARCH_BACKEND", "tavily")
    monkeypatch.setenv("TAVILY_API_KEY", "k")
    from wet_mcp.sources.search_backends import TavilyBackend, search_backend_from_env

    assert isinstance(search_backend_from_env(), TavilyBackend)
    with unittest.mock.patch("httpx.AsyncClient.post") as post:
        resp = unittest.mock.AsyncMock()
        resp.status_code = 200
        resp.json = unittest.mock.Mock(
            return_value={
                "results": [{"url": "https://x", "title": "t", "content": "c"}]
            }
        )
        post.return_value = resp
        import json

        out = json.loads(await search_backend_from_env().search("q"))
        assert out["results"][0]["url"] == "https://x"


def test_outbound_latency_under_budget():
    import time

    delays = {"count": 0}

    class SlowHttp(FakeD1Http):
        def request(self, method, url, data=None, headers=None):
            time.sleep(0.02)
            delays["count"] += 1
            return super().request(method, url, data, headers)

    d1 = D1Backend("http://d1.internal", http=SlowHttp(DDL))
    vec = VectorizeBackend(
        "http://vectorize.internal", idx="wet", http=FakeVectorizeHttp()
    )
    db = _cf_db(d1, vec)
    db.upsert_library("alpha")
    lib = db.get_library("alpha")
    # upsert_version returns the id directly. get_best_version means "best
    # INDEXED version", and this row does not reach status='indexed' until
    # mark_version_indexed runs, so it is the wrong way to fetch a fresh row.
    ver_id = db.upsert_version(lib["id"], "1.0")
    db.add_chunks(
        ver_id,
        lib["id"],
        [
            {
                "id": "c1",
                "url": "u",
                "title": "t",
                "chunk_index": 0,
                "content": "async function",
                "heading_path": "h",
            }
        ],
        embeddings=None,
    )
    start = time.monotonic()
    db.search("function", limit=5)
    assert (time.monotonic() - start) < 0.5


def test_jwt_sub_persists_across_container_recreate():
    # Deterministic-signing-key fix shipped in mcp-core 1.18.0b4+ (pinned here at
    # 1.18.0b5). With credential_secret set, JWTIssuer derives an Ed25519 key from
    # CREDENTIAL_SECRET via HKDF with NO disk I/O, so a recreated container (same
    # secret, no shared volume) converges on the same key and prior tokens stay valid.
    from mcp_core.oauth.jwt_issuer import JWTIssuer

    secret = "stable-secret"
    issuer1 = JWTIssuer(server_name="wet-mcp", credential_secret=secret)
    token = issuer1.issue_access_token("user@example.com")
    issuer2 = JWTIssuer(server_name="wet-mcp", credential_secret=secret)
    assert issuer2.verify_access_token(token)["sub"] == "user@example.com"
