# wet-mcp Architecture

> Status: Phase 1 (v&lt;auto&gt;+).
> Spec source: `~/projects/.superpower/wet-mcp/2026-04-19-wet-v2-design.md`.

This document describes the runtime architecture of wet-mcp after the
Phase 1 migration to `n24q02m-web-core` `ScrapingAgent`. It covers the
component graph, strategy escalation chain, storage layout, and LLM
provider dispatch model.

## Component graph

```text
wet-mcp client (Claude Code / Codex / Cursor / Antigravity)
    |
    | MCP protocol (stdio or HTTP)
    v
wet-mcp server (FastMCP)
    |
    +-- search tool   ----> sources/searxng.py + cache.py (TTL 1h / 5min)
    |                          |
    |                          v
    |                       SearXNG (bundled subprocess on port 41592)
    |
    +-- extract tool  ----> sources/crawler.py
    |                          |
    |                          v
    |                       web_core.scraper.ScrapingAgent
    |                          |
    |                          | strategy chain (escalation)
    |                          v
    |                       basic_http -> tls_spoof -> headless (Crawl4AI)
    |                          |
    |                          v
    |                       raw HTML / Markdown
    |                          |
    |                          v
    |                       sources/_smart_chunks.py (post-process)
    |                          |
    |                          v
    |                       { clean_text, markdown, structured_data,
    |                         code_blocks, metadata }
    |
    +-- media tool    ----> sources/crawler.py
    |                          |
    |                          +-- list:     web_core.scraper helpers
    |                          +-- download: SSRF-safe via web-core
    |                          +-- analyze:  DEPRECATED -> imagine-mcp.understand
    |
    +-- config tool   ----> mcp_core relay + config.py + cache management
    |
    +-- help tool     ----> src/wet_mcp/docs/{search,extract,media,config}.md
```

## Strategy escalation chain (extract pipeline)

`ScrapingAgent` walks the chain in order, stopping at the first strategy
that returns content above the quality threshold. Higher tiers cost more
in latency / browser memory / external API budget, so cheaper tiers run
first.

| Tier | Strategy | Cost | Success rate (tier-1 popular sites) |
|---|---|---|---|
| 0 | `basic_http` (httpx + standard headers) | very low | ~60% |
| 1 | `tls_spoof` (`curl_cffi` impersonation) | low | ~85% |
| 2 | `headless` (Crawl4AI Playwright) | medium | ~95% |

Phase 3 (planned, BREAKING) extends with `patchright` (stealth
interactive) and `captcha` (CapSolver) tiers per spec section 4.2.

### Rationale (cost vs success rate)

- **Latency budget**: each tier roughly 5x the previous tier's wall-clock
  cost. Always start cheap.
- **Browser bot detection**: many sites detect headless Chromium, but
  `tls_spoof` slips through TLS fingerprint checks at minimal cost.
- **Crawl4AI fallback**: serves the long tail (JS-heavy SPAs,
  infinite-scroll, dynamic loaders).
- **Markitdown bridge**: low-tier raw HTML routed through markitdown for
  HTML -> Markdown conversion when web-core does not supply MD natively.

### Smart chunks output schema

Every extract call returns a structured dict (no raw HTML leakage):

```json
{
  "clean_text": "Plain text extraction with whitespace normalized",
  "markdown": "Header- and list-aware markdown rendering",
  "structured_data": {
    "json_ld": [...],
    "open_graph": {...},
    "schema_org": {...}
  },
  "code_blocks": [
    {"language": "python", "content": "..."},
    {"language": "javascript", "content": "..."}
  ],
  "metadata": {
    "url": "https://example.com/article",
    "title": "Article title",
    "author": "...",
    "published_at": "...",
    "strategy_used": "tls_spoof",
    "fetched_at": 1747000000
  }
}
```

Heading extraction, code-block language detection, and JSON-LD parsing
live in `src/wet_mcp/sources/_smart_chunks.py`.

## Storage layout

| File | Purpose | Backend |
|---|---|---|
| `~/.wet-mcp/docs.db` | Library docs index (chunks + embeddings) | SQLite WAL + sqlite-vec |
| `~/.wet-mcp/cache.db` | Web search + extract cache (TTL gated) | SQLite WAL |
| `~/.wet-mcp/config.enc` | Encrypted credentials (mcp-core managed) | AES-GCM, machine-bound key |
| `~/.wet-mcp/downloads/` | Media download output dir | Filesystem |
| `~/.wet-mcp/tokens/google_drive.json` | OAuth Device Code token (sync) | Filesystem 0600 perms |

SearXNG runs as a bundled subprocess on `localhost:41592` (configurable
via `WET_SEARXNG_PORT`). It is not persisted across restarts; SearXNG
internal state is ephemeral.

Future Phase 2 schema additions (libraries, versions, project_context)
documented in spec section 5.4 -- migrations land via Alembic
revisions `docs_002_libraries`, `docs_003_project_context`.

## LLM provider dispatch (no hardcoded default)

Per spec section 5.5, wet-mcp does not pin a default LLM model. Provider
selection at runtime walks env vars in priority order:

```text
GEMINI_API_KEY / GOOGLE_API_KEY  -> google-genai SDK
OPENAI_API_KEY                   -> openai SDK
ANTHROPIC_API_KEY                -> anthropic SDK
XAI_API_KEY                      -> openai SDK (with base_url override)
LLM_MODELS env                   -> explicit comma-separated fallback chain
```

If none is set:

- `extract` selector inference falls back to heuristic rules + logs a
  warning.
- Core search/extract/docs continue to work via embedding-only ranking.
- No hard failure -- LLM is an enhancement, not a requirement.

This dispatch is shared with web-core's `selector_inference` module
(per spec section 5.5; web-core 2.0.1+ removed the hardcoded
`gemini-2.5-flash` default).

## Mode matrix

| Mode | Default? | Storage scope | Multi-user |
|---|---|---|---|
| stdio | Yes | Local user (`~/.wet-mcp/config.enc`, perm 0600) | No |
| HTTP self-host | No | Per-JWT-sub credential vault | Yes |

Spec section 5.2 + 5.3 cover the entry points and tool surface. The
stdio default avoids OAuth complexity for single-machine personal use;
HTTP self-host is recommended when multi-device sync, claude.ai web
compatibility, or team sharing matters.

## Cross-references

- Spec: `~/projects/.superpower/wet-mcp/2026-04-19-wet-v2-design.md` (sections 5.1, 5.4, 5.5, 5.6)
- Phase 1 plan: `~/projects/.superpower/wet-mcp/2026-05-09-phase-1-plan.md`
- Web-core repo: `n24q02m/web-core` (`web_core.scraper.ScrapingAgent`)
- mcp-core repo: `n24q02m/mcp-core` (relay, JWT issuer, config storage primitives)
- Trust model: <https://github.com/n24q02m/mcp-core/blob/main/docs/TRUST-MODEL.md>
