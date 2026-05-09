# wet-mcp Benchmarks

> Status: Phase 1 (v&lt;auto&gt;+) baseline. Target metrics defined in
> `~/projects/.superpower/wet-mcp/2026-04-19-wet-v2-design.md` section 3.

This document captures the v1.x baseline metrics established during
Phase 1. Full pre-release benchmark runs (latency p50 / p95, recall@10,
freshness, success rate against the 200-URL tier-1 fixture) land in the
pre-release main session per Plan 2026-05-09 Task 5 + Task 4.

## v1.x baseline (2026-05-09)

| Pillar | Metric | Value | Method |
|---|---|---|---|
| Coverage | `pytest --cov` post-Phase-1 | 93.24% | CI gate currently 93%, target post-Phase-1 95% (spec section 3) |
| Test suite | Total tests passed | 1606 | `uv run pytest` (unit + integration; e2e + benchmark + live excluded) |
| Test suite | Total tests skipped | 34 | Skips driven by missing optional creds (cloud APIs) |
| Tier-1 extract | Sample fixture size | 20 URLs | Sampled subset; full 200 URL fixture pending pre-release run |
| Tier-1 extract | Success rate (sample) | >=80% | Spec target 95% on full 200 URL fixture (section 3) |

## Latency placeholders

Real measurements land in pre-release benchmark CI run. Targets per spec
section 3:

| Pillar | Metric | Target | Methodology |
|---|---|---|---|
| Search | Query p95 (query -> embed rerank -> return) | < 2 s | 500 diverse queries fixture |
| Extract | Tier-1 success rate | >= 95% | 200 URL fixture, diverse domains |
| Extract | Tier-2 (Cloudflare/captcha) success rate | >= 70% with CapSolver / >= 50% without | 50 defended-site URL fixture |
| Extract | Markdown clean ratio (content/total chars) | >= 0.70 | 100 news/blog fixture, manual ground truth |
| Overall | Startup time (warm cache) | < 1 s | `uv run` -> first MCP initialize |
| Overall | Memory footprint (idle server) | < 400 MB | RSS after startup + 10 tool calls |
| Overall | Test coverage | >= 95% | `pytest --cov-fail-under=95` enforced in CI |

## Phase 1 gate notes

- **Coverage gate**: CI currently enforces `--cov-fail-under=93`. The
  `>=95%` spec target unlocks once the 200-URL tier-1 fixture is
  finalized (Plan Task 4 step 7) and exercised by the integration suite.
- **Tier-1 fixture**: 20-URL sample committed in Task 4. Full 200-URL
  fixture deferred to pre-release main session (per Plan Task 5 + Task 4).
- **Search polish (Task 5)**: query expansion + TTL cache (3600 s general
  / 300 s time-sensitive) + standardized citation format + 200-token
  snippet cap landed in commit `10f1ca5`.
- **ScrapingAgent migration (Task 4)**: extract pipeline now backed by
  `n24q02m-web-core` `ScrapingAgent` 5-strategy chain. Markdown output
  comparable to prior Crawl4AI-direct config across the sample fixture;
  full A/B comparison runs in pre-release main session.
- **Media slim (Task 6)**: `media.analyze` deprecated with grace-period
  message forwarding to `imagine-mcp.understand`. `list` + `download`
  unchanged.

## Pre-release benchmark plan

See spec section 7 for the full benchmark + fixture layout. The pre-release
benchmark CI job runs:

1. `tests/fixtures/urls/tier1_popular/` (200 URLs across diverse popular
   domains) -- success rate + markdown clean ratio.
2. `tests/fixtures/urls/tier2_defended/` (50 Cloudflare/captcha URLs) --
   success rate with and without CapSolver.
3. `tests/fixtures/queries/search_general/` (500 queries) -- p95 latency
   and recall@10 against curated ground truth.
4. `tests/fixtures/queries/search_time_sensitive/` (50 "today/latest"
   queries) -- freshness metric.
5. Startup time + idle memory snapshot.

Results write to `tests/fixtures/benchmarks/history/<timestamp>.json` and
get diff'd against the previous run for regression alerting.

## Cross-references

- Spec: `~/projects/.superpower/wet-mcp/2026-04-19-wet-v2-design.md` (section 3 metrics, section 7 fixture layout)
- Phase 1 plan: `~/projects/.superpower/wet-mcp/2026-05-09-phase-1-plan.md` (Task 4 step 7 fixture, Task 5 step 6 search benchmark, Task 8 pre-release gate)
