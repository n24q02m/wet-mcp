"""HTTP client for Cloudflare Vectorize v2 via the Worker outbound-handler.

upsert: POST {base}/upsert (ndjson lines {id, values, metadata}) -> {"mutationId": ...}
query:  POST {base}/query json {vector, topK, filter} -> {"matches": [{id, score, metadata}]}
delete: POST {base}/deleteByIds json {ids} -> {"mutationId": ...}
ready:  GET  {base} -> {"ready": bool}
Upsert is eventual (~seconds); add_chunks() callers must wait_until_indexed()
before asserting search results. Fail-loud on non-200.
"""

from __future__ import annotations

import json
import os
import time

import httpx

# Ids per `POST /deleteByIds` request. Cloudflare documents no hard id count for
# this endpoint, so this is a client-side bound only -- it keeps re-indexing a
# large version from building one enormous request body, and can be raised.
VECTORIZE_DELETE_CHUNK = 500


class _HttpxHttp:
    def request(self, method, url, data=None, headers=None):
        resp = httpx.request(
            method, url, content=data, headers=headers or {}, timeout=30.0
        )
        return (resp.status_code, resp.content)


class VectorizeBackend:
    def __init__(
        self, base_url: str, idx: str, token: str | None = None, http=None
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.idx = idx
        self._token = token
        self._http = http or _HttpxHttp()

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self._token}"} if self._token else {}

    def upsert(self, vectors: list[dict]) -> str:
        ndjson = "\n".join(json.dumps(v) for v in vectors).encode()
        status, data = self._http.request(
            "POST", f"{self.base_url}/upsert", ndjson, self._headers()
        )
        if status != 200:
            raise RuntimeError(f"VectorizeBackend upsert failed: HTTP {status}")
        return json.loads(data.decode()).get("mutationId", "")

    def query(
        self, vector: list[float], top_k: int, metadata_filter: dict | None = None
    ) -> list[dict]:
        # Vectorize caps topK at 50 when returning values/metadata.
        top_k = min(top_k, 50)
        body = json.dumps(
            {"vector": vector, "topK": top_k, "filter": metadata_filter or {}}
        ).encode()
        status, data = self._http.request(
            "POST", f"{self.base_url}/query", body, self._headers()
        )
        if status != 200:
            raise RuntimeError(f"VectorizeBackend query failed: HTTP {status}")
        return json.loads(data.decode()).get("matches", [])

    def delete_by_ids(self, ids: list[str]) -> list[str]:
        """Delete vectors by id; returns one mutation id per request sent.

        Fail-loud like upsert/query. A caller deleting chunk rows must be able
        to tell that the matching vectors did NOT go: vectors left behind
        outlive their content and come back as search hits with nothing to
        show for them.
        """
        mutations: list[str] = []
        for i in range(0, len(ids), VECTORIZE_DELETE_CHUNK):
            body = json.dumps({"ids": ids[i : i + VECTORIZE_DELETE_CHUNK]}).encode()
            status, data = self._http.request(
                "POST", f"{self.base_url}/deleteByIds", body, self._headers()
            )
            if status != 200:
                raise RuntimeError(
                    f"VectorizeBackend deleteByIds failed: HTTP {status}"
                )
            mutations.append(json.loads(data.decode()).get("mutationId", ""))
        return mutations

    def wait_until_indexed(
        self, poll_interval: float = 1.0, max_wait: float = 30.0
    ) -> bool:
        deadline = time.monotonic() + max_wait
        while time.monotonic() <= deadline:
            status, data = self._http.request(
                "GET", self.base_url, None, self._headers()
            )
            if status == 200 and json.loads(data.decode()).get("ready"):
                return True
            if poll_interval:
                time.sleep(poll_interval)
        return False


def vectorize_backend_from_env() -> VectorizeBackend:
    base = os.environ.get("MCP_VECTORIZE_BASE_URL", "http://vectorize.internal")
    idx = os.environ["MCP_VECTORIZE_IDX"]  # required when DOCS_DB_BACKEND=cf-d1
    return VectorizeBackend(
        base_url=base, idx=idx, token=os.environ.get("MCP_VECTORIZE_TOKEN")
    )


__all__ = ["VectorizeBackend", "vectorize_backend_from_env"]
