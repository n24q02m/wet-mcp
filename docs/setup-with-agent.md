# WET (Web Extended Toolkit) -- Agent Setup Guide

> Give this file to your AI agent to automatically set up wet-mcp.

> **Phase 1 (v&lt;auto&gt;+)**: Plugin install (Method 1) uses stdio mode.
> Basic SearXNG search works without env; advanced features (cloud
> embedding, multi-provider LLM, GDrive sync) need optional env vars OR
> HTTP mode for OAuth flows. Extract pipeline backed by `n24q02m-web-core`
> `ScrapingAgent` 5-strategy chain.

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
> create duplicate entries in `/mcp` because plugin matches by endpoint
> (URL or command string), not by name. Trade-off: choosing Method 2 or
> Method 3 means you lose the plugin's skills/agents/hooks/commands.

## Install snippets per client

### Claude Code (Method 1, plugin install)

```bash
/plugin marketplace add n24q02m/claude-plugins
/plugin install wet-mcp@n24q02m-plugins
```

CC will prompt you for optional `userConfig` credentials at install
(`JINA_AI_API_KEY`, `GEMINI_API_KEY`, `OPENAI_API_KEY`,
`ANTHROPIC_API_KEY`, `XAI_API_KEY`, `COHERE_API_KEY`, `GITHUB_TOKEN`).
Press Enter to skip any optional field.

### Claude Code (Method 1, CLI direct)

```bash
claude mcp add wet -- uvx wet-mcp
```

Then set env vars in your CC settings if desired:

```json
{
  "mcpServers": {
    "wet": {
      "command": "uvx",
      "args": ["wet-mcp"],
      "env": {
        "JINA_AI_API_KEY": "your_key_here",
        "GEMINI_API_KEY": "your_key_here"
      }
    }
  }
}
```

### Codex CLI

Add to `~/.codex/config.toml`:

```toml
[mcp_servers.wet]
command = "uvx"
args = ["wet-mcp"]

[mcp_servers.wet.env]
JINA_AI_API_KEY = "your_key_here"
GEMINI_API_KEY = "your_key_here"
```

### Cursor

Add to `~/.cursor/mcp.json`:

```json
{
  "mcpServers": {
    "wet": {
      "command": "uvx",
      "args": ["wet-mcp"],
      "env": {
        "JINA_AI_API_KEY": "your_key_here",
        "GEMINI_API_KEY": "your_key_here"
      }
    }
  }
}
```

### Antigravity

Use the [n24q02m/claude-plugins](https://github.com/n24q02m/claude-plugins)
marketplace if your Antigravity build supports the plugin loader; otherwise
add a manual MCP server entry to your Antigravity workspace settings using
the same `command` + `args` + `env` shape as the Cursor snippet above
(Antigravity follows the standard `mcpServers` schema).

### Method 2: Docker stdio

> **Before adding the Docker stdio override below, ensure this plugin is
> NOT installed via marketplace**: Run `/plugin uninstall
> wet-mcp@n24q02m-plugins` first.

```bash
docker run -i --rm \
  --name mcp-wet \
  -v wet-data:/data \
  -e JINA_AI_API_KEY \
  -e GEMINI_API_KEY \
  -e OPENAI_API_KEY \
  -e COHERE_API_KEY \
  -e BRAVE_API_KEY \
  -e SERPER_API_KEY \
  -e GITHUB_TOKEN \
  n24q02m/wet-mcp:latest
```

Or as an MCP server config:

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

### Method 3: Docker HTTP (multi-device, OAuth)

```bash
docker run -d --name wet-mcp-http \
  -p 8084:8084 \
  -v wet-data:/data \
  -e MCP_TRANSPORT=http \
  -e PUBLIC_URL=https://wet.example.com \
  -e MCP_DCR_SERVER_SECRET=your-random-secret \
  n24q02m/wet-mcp:latest
```

MCP client config:

```json
{
  "mcpServers": {
    "wet": {
      "url": "https://wet.example.com/mcp"
    }
  }
}
```

On first call, the client redirects to the relay form. Fill in API keys
(all optional) and -- if `SYNC_ENABLED=true` -- complete the GDrive
device-code flow using the bundled public Desktop client. Each user
receives an isolated credential vault keyed by JWT sub.

### Edge auth: relay password

Public HTTP deployments expose `<your-domain>/authorize` to URL discovery.
To prevent random Internet users from accessing the relay form, mint a
relay password:

```bash
openssl rand -hex 32
# Save in your skret / .env as:
MCP_RELAY_PASSWORD=<generated-32-byte-hex>
```

Share this password out-of-band with anyone you invite to use your server.
Once logged in, the cookie persists 24 hours.

**Single-user dev exception**: If `PUBLIC_URL=http://localhost:8084`, you
can leave `MCP_RELAY_PASSWORD` empty to disable the gate.

## Environment variables

All environment variables are **optional**. The server works in local mode
(ONNX embedding + bundled SearXNG) with zero configuration.

### LLM provider (multi-provider auto-detect)

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

### API keys (cloud providers)

| Variable | Required | Default | Description |
|---|---|---|---|
| `JINA_AI_API_KEY` | No | -- | Jina AI: search + extraction + embedding + reranking (highest priority) |
| `GEMINI_API_KEY` | No | -- | Gemini: LLM + embedding (free tier) |
| `OPENAI_API_KEY` | No | -- | OpenAI: LLM + embedding |
| `ANTHROPIC_API_KEY` | No | -- | Anthropic Claude: LLM (selector inference) |
| `XAI_API_KEY` | No | -- | xAI Grok: LLM (selector inference) |
| `COHERE_API_KEY` | No | -- | Cohere: embedding + reranking |
| `BRAVE_API_KEY` | No | -- | Brave Search API key (premium search) |
| `SERPER_API_KEY` | No | -- | Serper search API key (premium search) |
| `GITHUB_TOKEN` | No | auto-detect | GitHub token for docs discovery (60 -> 5000 req/hr). Auto-detected from `gh auth token` |

### Embedding and reranking

| Variable | Required | Default | Description |
|---|---|---|---|
| `EMBEDDING_BACKEND` | No | auto | `cloud` or `local` (Qwen3). Auto: API keys present -> cloud, else local |
| `EMBEDDING_MODEL` | No | auto | Cloud embedding model name |
| `EMBEDDING_DIMS` | No | `0` (auto = 768) | Embedding dimensions |
| `RERANK_ENABLED` | No | `true` | Enable reranking after search |
| `RERANK_BACKEND` | No | auto | `cloud` or `local`. Auto: Cohere/Jina key -> cloud, else local |
| `RERANK_MODEL` | No | auto | Cloud rerank model name |
| `RERANK_TOP_N` | No | `10` | Return top N results after reranking |

### SearXNG

| Variable | Required | Default | Description |
|---|---|---|---|
| `WET_AUTO_SEARXNG` | No | `true` | Auto-start embedded SearXNG subprocess |
| `WET_SEARXNG_PORT` | No | `41592` | SearXNG port |
| `SEARXNG_URL` | No | `http://localhost:41592` | External SearXNG URL (when auto disabled) |
| `SEARXNG_TIMEOUT` | No | `30` | SearXNG request timeout in seconds |

### File conversion

| Variable | Required | Default | Description |
|---|---|---|---|
| `CONVERT_MAX_FILE_SIZE` | No | `104857600` | Max file size for local conversion in bytes (100 MB) |
| `CONVERT_ALLOWED_DIRS` | No | -- | Comma-separated paths to restrict local file conversion |

### Storage and cache

| Variable | Required | Default | Description |
|---|---|---|---|
| `CACHE_DIR` | No | `~/.wet-mcp` | Data directory for cache, docs, downloads |
| `DOCS_DB_PATH` | No | `~/.wet-mcp/docs.db` | Docs database location |
| `DOWNLOAD_DIR` | No | `~/.wet-mcp/downloads` | Media download directory |
| `TOOL_TIMEOUT` | No | `120` | Tool execution timeout in seconds (0 = no timeout) |
| `WET_CACHE` | No | `true` | Enable/disable web cache (search uses 1 h general / 5 min time-sensitive TTL) |

### Google Drive sync

| Variable | Required | Default | Description |
|---|---|---|---|
| `SYNC_ENABLED` | No | `false` | Enable Google Drive sync |
| `GOOGLE_DRIVE_CLIENT_ID` | No | bundled public client | OAuth client ID. HTTP mode auto-uses bundled public Desktop client |
| `GOOGLE_DRIVE_CLIENT_SECRET` | No | bundled public secret | OAuth client secret (Desktop public client per Google docs) |
| `SYNC_FOLDER` | No | `wet-mcp` | Google Drive folder name |
| `SYNC_INTERVAL` | No | `300` | Auto-sync interval in seconds (0 = manual) |

### General

| Variable | Required | Default | Description |
|---|---|---|---|
| `LOG_LEVEL` | No | `INFO` | Logging level |
| `MCP_TRANSPORT` | No | `stdio` | Transport: `stdio` (default) or `http` |
| `PUBLIC_URL` | No | -- | HTTP mode: public URL of the server (required for multi-user OAuth) |
| `MCP_DCR_SERVER_SECRET` | No | -- | HTTP mode: random secret for Dynamic Client Registration JWT signing |
| `MCP_RELAY_PASSWORD` | No | -- | Relay form edge-auth password (HTTP mode, required for non-localhost `PUBLIC_URL`) |

## Authentication

### Stdio mode (default)

Set API keys directly as environment variables. Basic SearXNG search
works without any env. Advanced features (cloud embedding, multi-provider
LLM, premium search) activate when corresponding keys are set.
Credentials live only in the local process environment.

### HTTP mode (optional, multi-user)

After connecting an MCP client to the HTTP endpoint, the client redirects
to the relay form on first call:

1. Open the relay URL in any browser.
2. Fill in API keys on the guided form (all optional).
3. If `SYNC_ENABLED=true`, complete the GDrive device-code flow using the
   bundled public Desktop client (no user OAuth registration needed).
4. Credentials are encrypted per-JWT-sub and isolated per user.

Each user receives an isolated credential vault keyed by JWT sub.

## Verification

After setup, verify the server is working by calling the `search` tool:

```text
search(action="web", query="test query", limit=3)
```

Expected: returns standardized citation results with `title`, `url`,
`snippet`, `source_domain`, `published_at`, `freshness_signal`.
