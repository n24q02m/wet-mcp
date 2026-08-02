"""Eager Tier 1 docs ingestion for the curated library list.

Invoked manually or via CI weekly cron (.github/workflows/ci.yml).
Walks every entry in src/wet_mcp/data/tier1_libraries.json, calls
``ingest_tier2`` so doc chunks are pulled via the web-core
``library_docs_strategy`` chain (RTD / Docusaurus / Mintlify / GitHub
README), and rewrites a ``tier1_index_metrics.json`` summary alongside
``docs.db`` after every library, so an interrupted run still leaves the
libraries it did reach on disk (``"complete": false`` marks such a file).

Exits non-zero when fewer than ``--min-success-rate`` of the curated
libraries end up with at least one chunk, so a run that indexes nothing
fails its job instead of reporting success with an empty database.

Usage:

    uv run python scripts/build_tier1_index.py
    uv run python scripts/build_tier1_index.py --min-success-rate 0.5
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path
from typing import Any


async def _amain() -> int:
    parser = argparse.ArgumentParser(description="Eager Tier 1 docs ingestion")
    parser.add_argument(
        "--db-path",
        type=Path,
        default=Path.home() / ".wet-mcp" / "docs.db",
        help="Path to docs.db (default ~/.wet-mcp/docs.db)",
    )
    parser.add_argument(
        "--min-success-rate",
        type=float,
        default=0.8,
        help=(
            "Fraction of libraries that must yield at least one chunk for "
            "the run to succeed (default 0.8). Use 0 to never fail."
        ),
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
    # This line and every progress line below it flush explicitly. Python
    # block-buffers stdout when it is a pipe, which a CI log always is, so in
    # run 30736692116 the entire progress trace -- starting with this line --
    # was still sitting in the buffer when the runner was killed, and the log
    # kept only the loguru output that goes to stderr.
    print(f"Eager-ingesting {len(libraries)} Tier 1 libraries...", flush=True)

    metrics: list[dict[str, Any]] = []
    started = time.time()
    out_path = args.db_path.parent / "tier1_index_metrics.json"

    def write_metrics(*, complete: bool) -> dict[str, Any]:
        """Rewrite the metrics file from whatever has been collected so far.

        Called after every library rather than once at the end. A run that is
        cut short -- the CI job hitting its timeout, an unhandled crash, a
        cancel -- then leaves a readable record of how far it got instead of no
        file at all, which is what the 2026-08-02 canary failure left behind.
        ``complete`` is how a reader tells the two apart: in a partial file the
        aggregate counts describe only the libraries listed under ``metrics``,
        and ``success_rate`` is therefore a lower bound, not a verdict.

        The write goes to a sibling temp file and is renamed over the target,
        so being killed mid-write cannot replace a usable file with a
        truncated one.
        """
        indexed = [m for m in metrics if (m.get("chunk_count") or 0) > 0]
        summary = {
            "timestamp": time.time(),
            "complete": complete,
            "total_libraries": len(libraries),
            "libraries_attempted": len(metrics),
            "libraries_with_chunks": len(indexed),
            "success_rate": round(len(indexed) / len(libraries), 4)
            if libraries
            else 0.0,
            "min_success_rate": args.min_success_rate,
            "total_pages": sum(m.get("page_count") or 0 for m in metrics),
            "total_chunks": sum(m.get("chunk_count") or 0 for m in metrics),
            "duration_seconds": round(time.time() - started, 2),
            "metrics": metrics,
        }
        tmp_path = out_path.with_name(out_path.name + ".tmp")
        tmp_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
        tmp_path.replace(out_path)
        return summary

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
                f"({result.get('chunk_count', 0)} chunks, {duration:.1f}s)",
                flush=True,
            )
        except Exception as exc:  # pragma: no cover - script-level guard
            metrics.append({"library": name, "status": "error", "error": str(exc)})
            print(f"  {name}: ERROR {exc}", flush=True)
        write_metrics(complete=False)

    summary = write_metrics(complete=True)
    indexed = summary["libraries_with_chunks"]
    # Recomputed here rather than read back from the summary, which rounds:
    # the threshold below is a gate, so it compares the exact ratio.
    success_rate = indexed / len(libraries) if libraries else 0.0

    print("\n" + "=" * 60)
    print(
        f"Tier 1 index: {indexed}/{len(libraries)} libraries with chunks "
        f"({success_rate:.0%}), {summary['total_pages']} pages, "
        f"{summary['total_chunks']} chunks"
    )
    print(f"Metrics written to {out_path}")
    print("=" * 60)

    db.close()

    if success_rate < args.min_success_rate:
        # A run that indexes nothing used to exit 0 and paint CI green for
        # weeks while the database stayed empty.
        print(
            f"FAILED: success rate {success_rate:.0%} is below the "
            f"{args.min_success_rate:.0%} threshold",
            file=sys.stderr,
        )
        return 1
    return 0


def main() -> int:
    return asyncio.run(_amain())


if __name__ == "__main__":
    raise SystemExit(main())
