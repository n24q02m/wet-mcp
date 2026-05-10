"""Eager Tier 1 docs ingestion for the curated library list.

Invoked manually or via CI weekly cron (.github/workflows/ci.yml).
Walks every entry in src/wet_mcp/data/tier1_libraries.json, calls
``ingest_tier2`` so doc chunks are pulled via the web-core
``library_docs_strategy`` chain (RTD / Docusaurus / Mintlify / GitHub
README), and writes a ``tier1_index_metrics.json`` summary alongside
``docs.db``.

Usage:

    uv run python scripts/build_tier1_index.py
    uv run python scripts/build_tier1_index.py --upload-snapshot
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path


async def _amain() -> int:
    parser = argparse.ArgumentParser(description="Eager Tier 1 docs ingestion")
    parser.add_argument(
        "--db-path",
        type=Path,
        default=Path.home() / ".wet-mcp" / "docs.db",
        help="Path to docs.db (default ~/.wet-mcp/docs.db)",
    )
    parser.add_argument(
        "--upload-snapshot",
        action="store_true",
        help="Upload tier1_index_metrics.json to GitHub Releases (CI-only).",
    )
    args = parser.parse_args()

    # Lazy imports so script-only deps stay out of the runtime hot path.
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
    from wet_mcp.db import DocsDB
    from wet_mcp.migrations import run_migrations_on_startup
    from wet_mcp.sources.docs import ingest_tier2
    from wet_mcp.sources.tier1_warmup import _load_tier1_payload, maybe_warm

    args.db_path.parent.mkdir(parents=True, exist_ok=True)
    db = DocsDB(args.db_path, embedding_dims=0)
    run_migrations_on_startup(args.db_path)
    maybe_warm(db, force=True)

    payload = _load_tier1_payload()
    libraries = payload.get("libraries", [])
    print(f"Eager-ingesting {len(libraries)} Tier 1 libraries...")

    metrics = []
    started = time.time()
    for entry in libraries:
        name = entry["id"]
        t0 = time.time()
        try:
            result = await ingest_tier2(db, name)
            duration = time.time() - t0
            metrics.append(
                {
                    "library": name,
                    "status": result.get("status"),
                    "page_count": result.get("page_count", 0),
                    "chunk_count": result.get("chunk_count", 0),
                    "duration_seconds": round(duration, 2),
                }
            )
            print(
                f"  {name}: {result.get('status')} "
                f"({result.get('chunk_count', 0)} chunks, {duration:.1f}s)"
            )
        except Exception as exc:  # pragma: no cover - script-level guard
            metrics.append({"library": name, "status": "error", "error": str(exc)})
            print(f"  {name}: ERROR {exc}")

    summary = {
        "timestamp": time.time(),
        "total_libraries": len(libraries),
        "duration_seconds": round(time.time() - started, 2),
        "metrics": metrics,
    }
    out_path = args.db_path.parent / "tier1_index_metrics.json"
    out_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"\nWrote metrics to {out_path}")

    if args.upload_snapshot:
        # Best-effort: only used by CI. Local users can ignore.
        print("Snapshot upload requested (CI-only); see workflow for handler.")

    db.close()
    return 0


def main() -> int:
    return asyncio.run(_amain())


if __name__ == "__main__":
    raise SystemExit(main())
