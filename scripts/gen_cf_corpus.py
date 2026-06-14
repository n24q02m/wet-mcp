"""Generate the deterministic CF parity corpus + golden top-k from the SQLite baseline."""

import json
import tempfile
from pathlib import Path

OUT = Path(__file__).parent.parent / "tests" / "fixtures"
QUERIES = [
    "async function",
    "install the package",
    "error handling",
    "rate limit",
    "vector search",
]


def build_corpus() -> list[dict]:
    docs = []
    libs = ["alpha", "beta", "gamma", "delta", "epsilon"]
    templates = [
        "Define an async function {n} to handle requests with await and error handling.",
        "Install the package {n} via pip; configure the rate limit and retry policy.",
        "Vector search uses cosine similarity over embeddings of dimension 768 in {n}.",
        "Error handling: wrap calls in try/except and log the failure mode for {n}.",
        "Rate limit the batch loop to N requests per second to avoid 429 in {n}.",
    ]
    cid = 0
    for li, lib in enumerate(libs):
        for ver in ("1.0", "2.0", "3.0"):
            for ci in range(7):  # ~50 chunks per library across 3 versions
                t = templates[(li + ci) % len(templates)]
                docs.append(
                    {
                        "id": f"c{cid}",
                        "library": lib,
                        "version": ver,
                        "url": f"https://docs.example/{lib}/{ver}/page{ci // 3}",
                        "title": f"{lib} {ver} guide",
                        "chunk_index": ci,
                        "heading_path": f"{lib} > section {ci}",
                        "content": t.format(n=f"{lib}-{ver}-{ci}"),
                    }
                )
                cid += 1
    return docs


def main():
    from wet_mcp.db import DocsDB

    docs = build_corpus()
    OUT.mkdir(parents=True, exist_ok=True)
    # Trailing newline keeps the file end-of-file-fixer clean; `.splitlines()`
    # on read ignores it so the parsed doc count is unchanged.
    (OUT / "cf_corpus.jsonl").write_text("\n".join(json.dumps(d) for d in docs) + "\n")
    with tempfile.TemporaryDirectory() as tmp:
        db = DocsDB(Path(tmp) / "baseline.db", embedding_dims=768)
        for d in docs:
            lib_id = db.upsert_library(d["library"], docs_url=d["url"])
            # upsert_version returns the version_id directly; get_best_version
            # only returns rows stamped status='indexed', which this one-shot
            # generator never marks, so use the returned id (real baseline).
            ver_id = db.upsert_version(lib_id, d["version"])
            db.add_chunks(ver_id, lib_id, [d], embeddings=None)
        # store stable identity = (content prefix) so comparison is backend-neutral
        golden = {
            q: [r["content"][:40] for r in db.search(q, limit=10)] for q in QUERIES
        }
        (OUT / "cf_golden_topk.json").write_text(json.dumps(golden, indent=2))
        # Close the connection before the tempdir is removed so Windows can
        # unlink baseline.db (SQLite holds an OS-level handle while open).
        db.close()
    print(f"wrote {len(docs)} docs + golden for {len(QUERIES)} queries")


if __name__ == "__main__":
    main()
