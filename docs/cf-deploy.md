# Cloudflare deploy runbook (MCP servers)

Canonical, repeatable procedure to (re)deploy an MCP server's Cloudflare
Worker + Container. Covers the 6 CF-migrated servers: `wet`, `mnemo`, `imagine`,
`better-telegram`, `better-email`, `better-notion`. Companion to
[`cf-template.md`](./cf-template.md) (the worker code template + footguns).

> Real account/KV/D1/Vectorize IDs live ONLY in each repo's gitignored
> `wrangler.deploy.jsonc`. This doc uses `<account-id>` / `<...-id>` placeholders.

## Topology

| Domain shape | What it is | Caddy? |
|---|---|---|
| `wet.n24q02m.com` (short) | **CF Worker** (migration target) | no |
| `wet-mcp.n24q02m.com` (full repo name) | OCI legacy (CF Tunnel -> Caddy -> Docker), fallback | yes (`via: 1.1 Caddy` header) |

Each server is a Worker + per-`sub` Container Durable Object. State is
externalised so the container survives scale-to-zero / delete+recreate:

| concern | backend | env |
|---|---|---|
| creds + OAuth tokens | KV (`PerPluginStore` cf-kv) | `MCP_STORAGE_BACKEND=cf-kv`, `MCP_KV_BASE_URL=http://kv.internal` |
| memories / docs (mnemo, wet) | D1 | `DOCS_DB_BACKEND=cf-d1`, `MCP_D1_BASE_URL=http://d1.internal` |
| embedding vectors (mnemo, wet) | Vectorize | `MCP_VECTORIZE_BASE_URL=http://vectorize.internal`, `MCP_VECTORIZE_IDX` |

Two auth gates, both enforced (never disabled on shared infra):
- **Gate A** — relay password (`MCP_RELAY_PASSWORD`, skret `/oci-vm-prod/prod`); `/authorize` -> `/login`.
- **Gate B** — DCR + PKCE bearer (`/mcp` -> 401 without a token).

## Prerequisites

- **CF token** — skret `/n24q02m/dev` `CF_DEV_TOKEN` (account-scoped: workers
  scripts/containers/KV ok; canNOT edit zone DNS/routes). Inject, never print:
  ```bash
  MSYS_NO_PATHCONV=1 skret run -e dev --path=/n24q02m/dev -- bash -c \
    'export CLOUDFLARE_API_TOKEN="$CF_DEV_TOKEN"; <cmd>'
  ```
- `docker`, and `bunx wrangler` (downloaded on demand; works in Python repos too).
- **`wrangler.deploy.jsonc`** — gitignored copy of the committed placeholder
  `wrangler.jsonc` with real IDs filled. If missing, reconstruct from
  `wrangler.jsonc` + CF-queried IDs (`wrangler kv namespace list`,
  `wrangler d1 list`, `wrangler vectorize list`). NO `routes` block (custom
  domains are already attached); set `"workers_dev": false`. TS servers also
  need `HOST=0.0.0.0` + `PORT=8080` (core-ts binds 127.0.0.1 by default, so the
  container is otherwise unreachable).

## Deploy (one command)

```bash
MSYS_NO_PATHCONV=1 skret run -e dev --path=/n24q02m/dev -- bash -c \
  'export CLOUDFLARE_API_TOKEN="$CF_DEV_TOKEN"; python scripts/deploy_cf.py'
```

`scripts/deploy_cf.py` runs: `docker build --target http` -> tag to
`registry.cloudflare.com/<account-id>/<name>:<tag>` -> `wrangler containers push`
-> `wrangler deploy --config wrangler.deploy.jsonc` -> **poll until rollout
completes**. Flags: `--tag <tag>` (default `b-<short-sha>`), `--skip-build`,
`--dry-run`. The CF container registry only pulls from
`registry.cloudflare.com` (an external ghcr ref fails
`IMAGE_REGISTRY_NOT_CONFIGURED`), hence the tag-then-push step.

### Pinning mcp-core before a deploy

The container bakes `n24q02m-mcp-core` via `uv sync --frozen` (Python) /
`bun install` (TS), reading the **lockfile** — so a code fix in mcp-core only
reaches the container after bumping the pin and rebuilding:

```bash
# Python (wet, mnemo, imagine)
UV_NO_SOURCES=1 uv lock --upgrade-package n24q02m-mcp-core
# TS (telegram, email, notion)
bun update @n24q02m/mcp-core      # after setting ^<ver> in package.json
```

Pin to an ALREADY-PUBLISHED version (PSR generates it on mcp-core CD); never
hand-pick a version string. A STABLE mcp-core release auto-files "bump" issues
downstream; a BETA does not, so bump manually for betas.

## Rollout wait (critical)

`wrangler deploy` only registers the new image (application STATE ->
`provisioning`). The running Durable Object instances keep serving the **OLD**
image until recycled — slow for a heavy image (wet ~6GB). **Verify only after
`wrangler containers list` shows STATE=`ready`**, and do NOT load-test during
`provisioning` (sustained load pins old instances and delays the roll). A steady
(non-decaying) failure rate that matches an already-fixed bug = old instances
still serving, not a re-regression; confirm by grepping the fix inside the built
image (`docker run --rm --entrypoint sh <img> -c 'grep ... $(find / -name <file>)'`).
`deploy_cf.py` waits automatically.

## Verify

Protocol self-test (PRIMARY), not the CC harness:

```bash
MSYS_NO_PATHCONV=1 skret run -e prod --path=/oci-vm-prod/prod -- \
  skret run -e prod --path=/<server>/prod -- \
  uv run --no-project --with mcp --with httpx --with anyio \
  python scripts/cf_full_flow.py --endpoint https://<server>.n24q02m.com
```

- `mnemo` harness is `scripts/cf_full_flow_mnemo.py`; `notion` is delegated
  Notion OAuth (`bootstrap` -> user approves -> `exchange --landing "<url>"`).
- Invalid-sub regression check (no-retry, counts `_`-subs that save): the generic
  `~/.cf-verify/check.py` mints N subs and asserts `INVALID_SUB=0`.

## Per-server map

| Server | Worker / DO | Backends | Notable vars |
|---|---|---|---|
| wet | `wet-mcp-worker` / `WetContainer` | KV + D1 + Vectorize | `SEARCH_BACKEND`, `EMBEDDING/RERANK/LLM_MODELS` |
| mnemo | `mnemo-mcp-worker` / `MnemoContainer` | KV + D1 + Vectorize | `EMBEDDING_DIMS=768`, model chains |
| imagine | `imagine-mcp-worker` / `ImagineContainer` | KV | `IMAGINE_OUTPUT_MODE=base64` |
| telegram | `better-telegram-mcp-worker` / `TelegramContainer` | KV | `HOST=0.0.0.0`, `PORT=8080` |
| email | `better-email-mcp-worker` / `EmailContainer` | KV | `HOST=0.0.0.0`, `PORT=8080` |
| notion | `better-notion-mcp-worker` / `NotionContainer` | KV | `HOST=0.0.0.0`, `PORT=8080`, delegated OAuth |

Per-server secrets: `wrangler secret put` for `CREDENTIAL_SECRET`,
`MCP_RELAY_PASSWORD`, `MCP_DCR_SERVER_SECRET`, plus provider/OAuth keys. These
are NOT in `wrangler.deploy.jsonc` (only non-secret `vars` are).
