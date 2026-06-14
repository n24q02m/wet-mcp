"""Shared Cloudflare-pilot test fixtures: deterministic backend doubles + corpus."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


class FakeKvHttp:
    """Injectable http for mcp_core CfKvBackend / wet CfKvBackend.

    Implements `.request(method, url, data, headers) -> (status, body)` exactly
    as mcp-core's CfKvBackend expects (URL-encoded single-segment key).
    """

    def __init__(self) -> None:
        self.store: dict[str, bytes] = {}

    def request(self, method, url, data=None, headers=None):
        from urllib.parse import unquote

        key = unquote(url.rsplit("/", 1)[-1])
        if method == "PUT":
            self.store[key] = data or b""
            return (200, b"")
        if method == "GET":
            return (200, self.store[key]) if key in self.store else (404, b"")
        if method == "DELETE":
            existed = key in self.store
            self.store.pop(key, None)
            return (200, b"") if existed else (404, b"")
        raise AssertionError(f"unexpected method {method}")


class FakeD1Http:
    """Injectable http for wet D1Backend. Backs queries with a real in-memory
    sqlite that runs the EXACT db.py FTS5 DDL so FTS5/bm25 parity holds.
    Wire contract: POST <base>/query with json {"sql": str, "params": list}
    -> (200, json.dumps({"results": [<row dicts>]}).encode()).
    """

    def __init__(self, ddl_sql: str) -> None:
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(ddl_sql)

    def request(self, method, url, data=None, headers=None):
        assert method == "POST" and url.endswith("/query")
        payload = json.loads(data.decode())
        sql, params = payload["sql"], payload.get("params", [])
        cur = self.conn.execute(sql, params)
        rows = [dict(r) for r in cur.fetchall()] if cur.description else []
        self.conn.commit()
        return (200, json.dumps({"results": rows}).encode())


class FakeVectorizeHttp:
    """Injectable http for wet VectorizeBackend. Cosine-ranks in-memory vectors.
    upsert: POST <base>/upsert (ndjson lines {id, values, metadata}) -> mutationId.
    query:  POST <base>/query json {vector, topK, filter} -> {matches:[{id,score,metadata}]}.
    GET <base> -> {ready: bool} (eventual-consistency toggle via `ready_after`).
    """

    def __init__(self, ready_after: int = 0) -> None:
        self.vectors: dict[str, tuple[list[float], dict]] = {}
        self._ready_polls = ready_after

    @staticmethod
    def _cosine(a, b):
        dot = sum(x * y for x, y in zip(a, b, strict=False))
        na = sum(x * x for x in a) ** 0.5 or 1.0
        nb = sum(y * y for y in b) ** 0.5 or 1.0
        return dot / (na * nb)

    def request(self, method, url, data=None, headers=None):
        if method == "GET":
            ready = self._ready_polls <= 0
            self._ready_polls -= 1
            return (200, json.dumps({"ready": ready}).encode())
        if url.endswith("/upsert"):
            for line in data.decode().splitlines():
                rec = json.loads(line)
                self.vectors[rec["id"]] = (rec["values"], rec.get("metadata", {}))
            return (200, json.dumps({"mutationId": "mut-test"}).encode())
        if url.endswith("/query"):
            q = json.loads(data.decode())
            ranked = sorted(
                (
                    (cid, self._cosine(q["vector"], v))
                    for cid, (v, _m) in self.vectors.items()
                ),
                key=lambda t: t[1],
                reverse=True,
            )[: q["topK"]]
            matches = [
                {"id": cid, "score": s, "metadata": self.vectors[cid][1]}
                for cid, s in ranked
            ]
            return (200, json.dumps({"matches": matches}).encode())
        raise AssertionError(url)


@pytest.fixture
def fake_kv_http():
    return FakeKvHttp()


@pytest.fixture
def cf_env(monkeypatch):
    """Canonical CF env preset; secrets are dummies (never inline real ones)."""
    monkeypatch.setenv("CREDENTIAL_SECRET", "test-credential-secret")
    monkeypatch.setenv("MCP_STORAGE_BACKEND", "cf-kv")
    monkeypatch.setenv("MCP_KV_BASE_URL", "http://kv.internal")
    monkeypatch.setenv("DOCS_DB_BACKEND", "cf-d1")
    monkeypatch.setenv("MCP_D1_BASE_URL", "http://d1.internal")
    monkeypatch.setenv("MCP_VECTORIZE_BASE_URL", "http://vectorize.internal")
    monkeypatch.setenv("MCP_VECTORIZE_IDX", "wet-docs-test")
    monkeypatch.setenv("EMBEDDING_MODELS", "jina_ai/jina-embeddings-v5-text-small")
    monkeypatch.setenv("RERANK_MODELS", "jina_ai/jina-reranker-v3")
    monkeypatch.setenv("JINA_AI_API_KEY", "dummy-jina-key")
    monkeypatch.setenv("SEARCH_BACKEND", "tavily")
    monkeypatch.setenv("TAVILY_API_KEY", "dummy-tavily-key")


@pytest.fixture
def local_default_env(monkeypatch):
    """Backward-compat: no CF env -> LocalFs + sqlite."""
    for var in (
        "MCP_STORAGE_BACKEND",
        "MCP_KV_BASE_URL",
        "DOCS_DB_BACKEND",
        "SEARCH_BACKEND",
    ):
        monkeypatch.delenv(var, raising=False)


@pytest.fixture
def cf_corpus():
    return [
        json.loads(line)
        for line in (FIXTURES / "cf_corpus.jsonl").read_text().splitlines()
    ]


@pytest.fixture
def cf_golden_topk():
    return json.loads((FIXTURES / "cf_golden_topk.json").read_text())
