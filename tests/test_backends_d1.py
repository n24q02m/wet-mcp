import json

from wet_mcp.backends.d1 import D1Backend, d1_backend_from_env


def test_d1_execute_returns_rows():
    class Http:
        def request(self, method, url, data=None, headers=None):
            assert method == "POST" and url == "http://d1.internal/query"
            payload = json.loads(data.decode())
            assert payload["sql"].startswith("SELECT")
            assert payload["params"] == ["alpha"]
            return (
                200,
                json.dumps({"results": [{"id": "c1", "name": "alpha"}]}).encode(),
            )

    db = D1Backend(base_url="http://d1.internal", http=Http())
    rows = db.execute("SELECT * FROM libraries WHERE name = ?", ["alpha"])
    assert rows == [{"id": "c1", "name": "alpha"}]


def test_d1_executemany_chunks_large_batches():
    calls = []

    class Http:
        def request(self, method, url, data=None, headers=None):
            calls.append(json.loads(data.decode()))
            return (200, json.dumps({"results": []}).encode())

    db = D1Backend(base_url="http://d1.internal", http=Http(), max_rows_per_insert=2)
    db.executemany("INSERT INTO doc_chunks (id) VALUES (?)", [["a"], ["b"], ["c"]])
    assert len(calls) == 2  # 2 + 1 rows -> 2 batched POSTs


def test_d1_raises_on_http_error():
    class Http:
        def request(self, method, url, data=None, headers=None):
            return (500, b"")

    import pytest

    with pytest.raises(RuntimeError, match="D1Backend"):
        D1Backend(base_url="http://d1.internal", http=Http()).execute("SELECT 1", [])


def test_d1_backend_from_env(monkeypatch):
    monkeypatch.setenv("MCP_D1_BASE_URL", "http://d1.internal")
    assert d1_backend_from_env().base_url == "http://d1.internal"
