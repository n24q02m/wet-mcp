# WET (Web Extended Toolkit) -- Manual Setup Guide

> **Phase 1 (v&lt;auto&gt;+)**: Plugin install (Method 1) uses stdio mode.
> Basic SearXNG search works without env vars; advanced features (cloud
> embedding/reranking, multi-provider LLM, GDrive sync, Brave/Serper
> premium search) need optional env vars OR HTTP mode for OAuth flows.
> Extract pipeline backed by `n24q02m-web-core` `ScrapingAgent`
> 5-strategy chain (`basic_http` -> `tls_spoof` -> `headless`).

## Method overview

This plugin supports 3 install methods. Pick the one that matches your
use case:

| Priority | Method | Transport | Best for |
|---|---|---|---|
| **1. Default** | Plugin install (`uvx`) | stdio | Quick local start, single workstation, no OAuth/HTTP needed. |
| **2. Fallback** | Docker stdio (`docker run -i --rm`) | stdio | Windows/macOS where native uvx hits PATH or Python version issues. |
| **3. Recommended for HTTP** | Docker HTTP (`docker run -p 8084:8084`) | HTTP | Multi-device, OAuth/relay-form auth, team self-host, claude.ai web compatibility. |

> **Mutually exclusive -- pick ONE per plugin**: If you choose Method 2
> (Docker stdio override) OR Method 3 (HTTP), do NOT also `/plugin
> install` this plugin via marketplace. Both load simultaneously and
> create duplicate entries in `/mcp` because plugin matching is by
> endpoint (URL or command string), not by name (`uvx` != `docker` !=
> HTTP URL). Trade-off: choosing Method 2 or Method 3 means you lose
> this plugin's skills/agents/hooks/commands. For full plugin features,
> use Method 1.

## Prerequisites

- **Python 3.13** (3.14+ is NOT supported due to SearXNG incompatibility)
- `uv` or `uvx` installed -- see [docs.astral.sh/uv](https://docs.astral.sh/uv/getting-started/installation/)
- Docker (optional, for containerized setup)

## Method 1: Plugin install (stdio default)

For Claude Code users, the plugin approach is the simplest. Plugin install
uses **stdio mode** -- basic SearXNG web search works **without any env
vars**. Advanced features require optional API keys.

### Credential prompts at install

When you run `/plugin install`, Claude Code prompts you for the following
credentials (declared in `userConfig` per CC docs). Sensitive values are
stored in your system keychain and persist across `/plugin update`:

| Field | Required | Where to obtain |
|---|---|---|
| `JINA_AI_API_KEY` | Optional | <https://jina.ai/api-key> (highest priority embedding + reranking) |
| `GEMINI_API_KEY` | Optional | <https://aistudio.google.com/apikey> |
| `OPENAI_API_KEY` | Optional | <https://platform.openai.com/api-keys> |
| `ANTHROPIC_API_KEY` | Optional | <https://console.anthropic.com/settings/keys> |
| `XAI_API_KEY` | Optional | <https://console.x.ai> (Grok) |
| `COHERE_API_KEY` | Optional | <https://dashboard.cohere.com/api-keys> |
| `GITHUB_TOKEN` | Optional | <https://github.com/settings/tokens> (bumps GitHub rate limit 60->5000/hr for library docs discovery) |

### Steps

```bash
# Marketplace install (full plugin: skills + hooks + stdio MCP server)
/plugin marketplace add n24q02m/claude-plugins
/plugin install wet-mcp@n24q02m-plugins
```

After install, restart Claude Code -- the server starts automatically when
CC launches with the values injected.

Without env vars: SearXNG metasearch + content extraction (5-strategy
chain) + library docs + ONNX local embedding/reranking all work. With env
vars: cloud embedding/reranking (faster), multi-provider LLM (selector
inference fallback), premium search providers.

> **Note**: This installs the full plugin (skills + hooks + stdio MCP
> server). If you'd rather use Method 2 (Docker stdio) or Method 3
> (HTTP) below, DO NOT `/plugin install` this plugin -- pick Method 2
> or Method 3 instead. All three methods are mutually exclusive (see
> Method overview).

## Method 2: Docker stdio (fallback)

> **Before adding the Docker stdio override below, ensure this plugin is
> NOT installed via marketplace**: Run `/plugin uninstall
> wet-mcp@n24q02m-plugins` first if you previously ran `/plugin
> install`. Otherwise both entries (plugin's `uvx` stdio + your `docker
> run` stdio) will load simultaneously since plugin matches by endpoint
> (command string), not by name.

1. Pull the image:

   ```bash
   docker pull n24q02m/wet-mcp:latest
   ```

2. Run with environment variables:

   ```bash
   docker run -i --rm \
     --name mcp-wet \
     -v wet-data:/data \
     -e JINA_AI_API_KEY=your_key_here \
     -e GEMINI_API_KEY=your_key_here \
     n24q02m/wet-mcp:latest
   ```

3. Or add to your MCP client config:

   ```json
   {
     "mcpServers": {
       "wet": {
         "command": "docker",
         "args": [
           "run", "-i", "--rm",
           "--name", "mcp-wet",
           "-v", "wet-data:/data",
           "-e", "JINA_AI_API_KEY",
           "-e", "GEMINI_API_KEY",
           "-e", "GITHUB_TOKEN",
           "n24q02m/wet-mcp:latest"
         ]
       }
     }
   }
   ```

## Why upgrade to HTTP mode?

Stdio mode is the default and works for most personal/single-user
scenarios. Consider switching to HTTP mode (Method 3 self-host) when you
need:

- **claude.ai web compatibility** -- HTTP transport is required to
  connect plugins to claude.ai web client (stdio only works with
  desktop clients)
- **One server shared across N Claude Code sessions** -- single daemon
  serves all sessions instead of spawning a fresh stdio process per
  session (lower memory, shared cache)
- **Browser-based GDrive OAuth flow** -- HTTP mode performs the Google
  Device Code flow via the bundled public client; no manual
  `GOOGLE_DRIVE_CLIENT_ID` setup required
- **Multi-device credential sync** -- self-host the HTTP server once,
  log in from multiple machines without re-pasting API keys
- **Multi-user team sharing** -- single self-hosted instance supports N
  users with per-JWT-sub credential isolation
- **Always-on persistent process** -- ideal for webhooks, scheduled
  agents, or background automation

## Method 3: Docker HTTP (recommended for multi-device)

> **Before adding the HTTP override below, ensure this plugin is NOT
> installed via marketplace**: Run `/plugin uninstall
> wet-mcp@n24q02m-plugins` first if you previously ran `/plugin
> install`. Otherwise both entries (plugin's stdio + your HTTP override)
> will load simultaneously since plugin matches by endpoint, not name.

HTTP mode runs as a persistent multi-user server with browser-based
credential setup. GDrive OAuth uses a bundled public Google Desktop
client per Google's official Desktop OAuth pattern -- no user-side OAuth
registration is required. Users authenticate via the device-code flow in
their browser.

1. Run the server in HTTP mode:

   ```bash
   docker run -d --name wet-mcp-http \
     -p 8084:8084 \
     -v wet-data:/data \
     -e MCP_TRANSPORT=http \
     -e PUBLIC_URL=https://wet.example.com \
     -e MCP_DCR_SERVER_SECRET=your-random-secret \
     n24q02m/wet-mcp:latest
   ```

2. Configure your MCP client to connect to the HTTP endpoint:

   ```json
   {
     "mcpServers": {
       "wet": {
         "url": "https://wet.example.com/mcp"
       }
     }
   }
   ```

3. On first call, the client redirects to the relay form. Fill in API
   keys (all optional) and -- if `SYNC_ENABLED=true` -- complete the
   GDrive device-code flow in your browser using the bundled public
   client.

Each user receives an isolated credential vault keyed by JWT sub. No
per-user OAuth registration needed.

### Edge auth: relay password

Public HTTP deployments expose `<your-domain>/authorize` to URL
discovery. To prevent random Internet users from accessing the relay
form, mint a relay password:

```bash
openssl rand -hex 32
# Save in your skret / .env as:
MCP_RELAY_PASSWORD=<generated-32-byte-hex>
```

Share this password out-of-band (Signal/email/SMS) with anyone you
invite to use your server. They will see a login form when first opening
`/authorize`; once logged in, the cookie persists 24 hours.

**Single-user dev exception**: If `PUBLIC_URL=http://localhost:8084`,
you can leave `MCP_RELAY_PASSWORD` empty to disable the gate. The
server logs a warning if you skip the password with a non-localhost
`PUBLIC_URL`.

## Environment variables

All environment variables are **optional**. The server runs with zero
configuration via local ONNX embedding + bundled SearXNG.

### LLM provider (multi-provider auto-detect)

wet-mcp uses a multi-provider LLM dispatch (no hardcoded default). The
first env var with a value below activates that provider for selector
inference fallback in the extract chain:

| Variable | Provider | SDK |
|---|---|---|
| `GEMINI_API_KEY` / `GOOGLE_API_KEY` | Gemini | `google-genai` |
| `OPENAI_API_KEY` | OpenAI | `openai` |
| `ANTHROPIC_API_KEY` | Anthropic | `anthropic` |
| `XAI_API_KEY` | xAI (Grok) | `openai` (with base_url override) |
| `LLM_MODELS` | Optional override | Comma-separated provider/model fallback chain (e.g., `gemini/gemini-3-flash-preview,openai/gpt-5.4-mini`) |

If no LLM provider is configured, selector inference falls back to
heuristic rules + logs a warning. Core search/extract/docs still work via
embedding-only ranking.

### API keys (cloud providers, all optional)

| Variable | Default | Description |
|---|---|---|
| `JINA_AI_API_KEY` | -- | Jina AI: search + extraction + embedding + reranking (highest priority) |
| `GEMINI_API_KEY` | -- | Gemini: LLM + embedding (free tier) |
| `OPENAI_API_KEY` | -- | OpenAI: LLM + embedding |
| `ANTHROPIC_API_KEY` | -- | Anthropic Claude: LLM (selector inference) |
| `XAI_API_KEY` | -- | xAI Grok: LLM (selector inference) |
| `COHERE_API_KEY` | -- | Cohere: embedding + reranking |
| `BRAVE_API_KEY` | -- | Brave Search API key (premium search) |
| `SERPER_API_KEY` | -- | Serper search API key (premium search) |
| `GITHUB_TOKEN` | auto-detect | GitHub token for docs discovery (60 -> 5000 req/hr). Auto-detected from `gh auth token` |

### Transport + cache

| Variable | Default | Description |
|---|---|---|
| `MCP_TRANSPORT` | `stdio` | Transport: `stdio` (default) or `http` |
| `PUBLIC_URL` | -- | HTTP mode: public URL of the server (required for multi-user OAuth) |
| `MCP_DCR_SERVER_SECRET` | -- | HTTP mode: random secret for Dynamic Client Registration JWT signing |
| `MCP_RELAY_PASSWORD` | -- | Relay form edge-auth password (HTTP mode, required for non-localhost `PUBLIC_URL`) |
| `WET_CACHE` | `true` | Enable/disable web result + extract cache (search uses 1 h general / 5 min time-sensitive TTL) |
| `CACHE_DIR` | `~/.wet-mcp` | Data directory for cache, docs, downloads |
| `LOG_LEVEL` | `INFO` | Logging level (`DEBUG` / `INFO` / `WARNING` / `ERROR`) |

### SearXNG

| Variable | Default | Description |
|---|---|---|
| `WET_AUTO_SEARXNG` | `true` | Auto-start embedded SearXNG subprocess |
| `WET_SEARXNG_PORT` | `41592` | SearXNG port |
| `SEARXNG_URL` | `http://localhost:41592` | External SearXNG URL (when auto disabled) |
| `SEARXNG_TIMEOUT` | `30` | SearXNG request timeout in seconds |

### Embedding + reranking

| Variable | Default | Description |
|---|---|---|
| `EMBEDDING_BACKEND` | auto | `cloud` or `local` (Qwen3 ONNX). Auto: API keys present -> cloud, else local |
| `EMBEDDING_MODEL` | auto | Cloud embedding model name |
| `EMBEDDING_DIMS` | `0` (auto = 768) | Embedding dimensions |
| `RERANK_ENABLED` | `true` | Enable reranking after search |
| `RERANK_BACKEND` | auto | `cloud` or `local`. Auto: Cohere/Jina key -> cloud, else local |
| `RERANK_MODEL` | auto | Cloud rerank model name |
| `RERANK_TOP_N` | `10` | Return top N results after reranking |

### Google Drive sync

| Variable | Default | Description |
|---|---|---|
| `SYNC_ENABLED` | `false` | Enable Google Drive sync |
| `GOOGLE_DRIVE_CLIENT_ID` | bundled public client | OAuth client ID. HTTP mode auto-uses bundled public Desktop client |
| `GOOGLE_DRIVE_CLIENT_SECRET` | bundled public secret | OAuth client secret (Desktop public client per Google docs) |
| `SYNC_FOLDER` | `wet-mcp` | Google Drive folder name |
| `SYNC_INTERVAL` | `300` | Auto-sync interval in seconds (0 = manual) |

### File conversion

| Variable | Default | Description |
|---|---|---|
| `CONVERT_MAX_FILE_SIZE` | `104857600` | Max file size for local conversion in bytes (100 MB) |
| `CONVERT_ALLOWED_DIRS` | -- | Comma-separated paths to restrict local file conversion |

## Provider priority

- **Embedding**: Jina AI > Gemini > OpenAI > Cohere > Local ONNX (Qwen3)
- **Reranking**: Jina AI > Cohere > Local ONNX (Qwen3)
- **LLM (selector inference)**: Gemini > OpenAI > Anthropic > xAI > Disabled
- **Search**: Brave > Serper > Jina AI > SearXNG (always available locally)

## Troubleshooting

### Server fails to start with Python 3.14+

wet-mcp requires Python 3.13 due to SearXNG incompatibility. Always use
`--python 3.13` with uvx:

```bash
uvx --python 3.13 wet-mcp
```

### First run takes a long time

On first start, the server downloads:

- SearXNG search engine (~50 MB)
- Crawl4AI Playwright chromium browser (~280 MB, transitive via web-core)
- ONNX embedding and reranker models (~1.1 GB total)

Use the warmup command to pre-download: `config(action="warmup")`.

### SearXNG port conflict

If port 41592 is in use, change it:

```bash
export WET_SEARXNG_PORT=41593
```

### Docker volume permissions

If you encounter permission errors with the Docker volume:

```bash
docker run -i --rm -v wet-data:/data --user $(id -u):$(id -g) n24q02m/wet-mcp:latest
```

### Embedding model download fails

If ONNX model download fails behind a proxy, use cloud embedding instead
by setting any API key (e.g., `GEMINI_API_KEY`).

## Verification

After setup, verify the server is working by calling the `search` tool:

```text
search(action="web", query="test query", limit=3)
```

Expected: returns search results with titles, URLs, and standardized
citation snippets (`title`, `url`, `snippet`, `source_domain`,
`published_at`, `freshness_signal`).
