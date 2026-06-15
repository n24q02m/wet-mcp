from conftest_cf import FakeVectorizeHttp

from wet_mcp.backends.vectorize import VectorizeBackend, vectorize_backend_from_env


def test_upsert_then_query_cosine_ranks():
    http = FakeVectorizeHttp()
    vec = VectorizeBackend(base_url="http://vectorize.internal", idx="wet", http=http)
    vec.upsert(
        [
            {"id": "a", "values": [1.0, 0.0], "metadata": {"url": "u-a"}},
            {"id": "b", "values": [0.0, 1.0], "metadata": {"url": "u-b"}},
        ]
    )
    matches = vec.query([0.9, 0.1], top_k=2)
    assert matches[0]["id"] == "a"  # closest by cosine
    assert matches[0]["metadata"]["url"] == "u-a"


def test_wait_until_indexed_polls_until_ready():
    http = FakeVectorizeHttp(ready_after=2)  # not ready twice, then ready
    vec = VectorizeBackend(base_url="http://vectorize.internal", idx="wet", http=http)
    assert vec.wait_until_indexed(poll_interval=0.0, max_wait=1.0) is True


def test_query_raises_on_http_error():
    class Http:
        def request(self, method, url, data=None, headers=None):
            return (502, b"")

    import pytest

    with pytest.raises(RuntimeError, match="VectorizeBackend"):
        VectorizeBackend(
            base_url="http://vectorize.internal", idx="wet", http=Http()
        ).query([0.1], top_k=1)


def test_vectorize_backend_from_env(monkeypatch):
    monkeypatch.setenv("MCP_VECTORIZE_BASE_URL", "http://vectorize.internal")
    monkeypatch.setenv("MCP_VECTORIZE_IDX", "wet-docs")
    b = vectorize_backend_from_env()
    assert b.idx == "wet-docs"
