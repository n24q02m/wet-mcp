import json

from mcp_core.storage.d1 import D1Backend, d1_backend_from_env


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


def _statements(payload):
    """Flatten one captured POST body into the statements it carries.

    `/query` sends a single {"sql", "params"} object; `/batch` sends a list of
    them. The bound-parameter cap applies per statement either way.
    """
    return payload if isinstance(payload, list) else [payload]


def test_executemany_never_exceeds_d1_bound_param_cap():
    """No single D1 statement may carry more than 100 bound parameters.

    Chunking by row count alone blows the cap on any table wider than one
    column: the live doc_chunks INSERT writes 13 columns, so a full 100-row
    batch carried 1300 parameters. D1 answers non-200, D1Backend raises
    RuntimeError, and the indexing layer's broad `except Exception` logs and
    moves on -- so no chunk is ever written and no error reaches the user.
    """
    payloads = []

    class Http:
        def request(self, method, url, data=None, headers=None):
            payloads.append(json.loads(data.decode()))
            return (200, json.dumps({"results": []}).encode())

    cols = 13
    rows = [[f"r{r}c{c}" for c in range(cols)] for r in range(50)]
    sql = (
        "INSERT INTO doc_chunks (id, version_id, library_id, url, title,"
        " chunk_index, content, heading_path, section, topic, content_hash,"
        " token_count, created_at) VALUES (" + ",".join(["?"] * cols) + ")"
    )

    db = D1Backend(base_url="http://d1.internal", http=Http())
    db.executemany(sql, rows)

    over = [
        len(s["params"])
        for p in payloads
        for s in _statements(p)
        if len(s["params"]) > 100
    ]
    assert not over, f"statements exceeding D1's 100-parameter cap: {over}"

    # And every row must still arrive -- a cap honored by dropping rows would
    # be the same silent data loss in a new costume.
    sent = sum(len(s["params"]) for p in payloads for s in _statements(p))
    assert sent == 50 * cols


def test_executemany_batches_are_sized_from_column_count():
    """Rows per statement is derived from the data, not assumed.

    13 columns against a 100-parameter cap is 7 rows (91 params) per statement,
    so 50 rows go out as 8 statements. Asserting the arithmetic keeps a future
    column addition from silently re-crossing the cap.
    """
    payloads = []

    class Http:
        def request(self, method, url, data=None, headers=None):
            payloads.append(json.loads(data.decode()))
            return (200, json.dumps({"results": []}).encode())

    cols = 13
    rows = [[f"r{r}c{c}" for c in range(cols)] for r in range(50)]
    sql = "INSERT INTO doc_chunks (a) VALUES (" + ",".join(["?"] * cols) + ")"
    D1Backend(base_url="http://d1.internal", http=Http()).executemany(sql, rows)

    sizes = [len(s["params"]) // cols for p in payloads for s in _statements(p)]
    assert sizes == [7, 7, 7, 7, 7, 7, 7, 1]


def test_executemany_rejects_a_row_too_wide_to_bind():
    """A row wider than the cap cannot be sent at all -- say so, loudly.

    Silently splitting such a row across statements would write corrupt
    partial rows; returning quietly would write nothing.
    """
    import pytest

    class Http:
        def request(self, method, url, data=None, headers=None):
            raise AssertionError("must not reach the network")

    db = D1Backend(base_url="http://d1.internal", http=Http())
    with pytest.raises(ValueError, match="bound parameter"):
        db.executemany(
            "INSERT INTO wide VALUES (" + ",".join(["?"] * 101) + ")",
            [[f"c{i}" for i in range(101)]],
        )


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
