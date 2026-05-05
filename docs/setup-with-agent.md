# WET (Web Extended Toolkit) -- Agent Setup Guide

> **2026-05-02 Update (v&lt;auto&gt;+)**: Plugin install (Option 1) uses stdio mode. Basic SearXNG search works without env; advanced features (GDrive sync, Brave, Serper, Gemini) need optional env vars OR HTTP mode for OAuth flows.
> The previous "Zero-Config Relay" auto-spawn pattern has been removed.

> Give this file to your AI agent to automatically set up wet-mcp.

## Method overview

This plugin supports 3 install methods. Pick the one that matches your use case:

| Priority | Method | Transport | Best for |
|---|---|---|---|
| **1. Default** | Plugin install (`uvx`/`npx`) | stdio | Quick local start, single workstation, no OAuth/HTTP needed. |
| **2. Fallback** | Docker stdio (`docker run -i --rm`) | stdio | Windows/macOS where native uvx/npx hits PATH or Python version issues. |
| **3. Recommended** | Docker HTTP (`docker run -p 8080:8080`) | HTTP | Multi-device, OAuth/relay-form auth, team self-host, claude.ai web compatibility. |

All MCP servers across this stack share this priority hierarchy. Note: 2 plugins (`better-godot-mcp` and `better-code-review-graph`) only support Method 1 (stdio) -- they need direct host access to project files / repo paths and don't ship Docker / HTTP variants.

> **⚠️ Mutually exclusive — pick ONE per plugin**: If you choose Method 2 (Docker stdio override) OR Method 3 (HTTP), do NOT also `/plugin install` this plugin via marketplace. Both load simultaneously and create duplicate entries in `/mcp` dialog (plugin's stdio + your override). Plugin matching is by **endpoint** (URL or command string) per CC docs, not by name — and `npx`/`uvx` ≠ `docker` ≠ HTTP URL, so all three are distinct endpoints. Trade-off: choosing Method 2 or Method 3 means you lose this plugin's skills/agents/hooks/commands. For full plugin features, use Method 1 (default plugin install) with `userConfig` credentials prompted at install time.

## Option 1: Claude Code Plugin (stdio default)

Plugin install uses **stdio mode**. Basic SearXNG web search works **without any env vars** -- ONNX local embedding and reranking are bundled. Advanced features require optional API keys.

### Credential prompts at install

When you run `/plugin install`, Claude Code prompts you for the following credentials (declared in `userConfig` per CC docs). Sensitive values are stored in your system keychain and persist across `/plugin update`:

| Field | Required | Where to obtain |
|---|---|---|
| `JINA_AI_API_KEY` | Optional | https://jina.ai/api-key (highest priority embedding+reranking) |
| `GEMINI_API_KEY` | Optional | https://aistudio.google.com/apikey |
| `OPENAI_API_KEY` | Optional | https://platform.openai.com/api-keys |
| `COHERE_API_KEY` | Optional | https://dashboard.cohere.com/api-keys |
| `GITHUB_TOKEN` | Optional | https://github.com/settings/tokens (bumps GitHub rate limit 60->5000/hr for library docs discovery) |

### Steps

```bash
# Install from marketplace (includes skills: /fact-check, /compare)
/plugin marketplace add n24q02m/claude-plugins
/plugin install wet-mcp@n24q02m-plugins
```

> Other optional env vars (`BRAVE_API_KEY`, `SERPER_API_KEY`, `OPENAI_API_KEY`, `COHERE_API_KEY`, `GITHUB_TOKEN`, `SYNC_ENABLED`, etc.) are not part of the `userConfig` prompt; add them manually to `mcpServers.wet.env` in your settings if needed.

Without env vars: SearXNG metasearch + content extraction + library docs + ONNX embedding work out of the box. With env vars: cloud embedding/reranking, Gemini LLM analysis, premium search providers.

> **Note**: This installs the full plugin (skills + agents + hooks + commands + stdio MCP server). If you'd rather use Option 2 (Docker stdio) or Option 3 (HTTP) below, DO NOT `/plugin install` this plugin — pick Option 2 or Option 3 instead. All three methods are mutually exclusive (see Method overview).

## Option 2: Docker stdio (fallback)

> **⚠️ Before adding the Docker stdio override below, ensure this plugin is NOT installed via marketplace**: Run `/plugin uninstall wet-mcp@n24q02m-plugins` first if you previously ran `/plugin install`. Otherwise both entries (plugin's `npx`/`uvx` stdio + your `docker run` stdio) will load simultaneously since plugin matches by endpoint (command string), not by name.
>
> **Trade-off accepted**: Choosing this method means you lose this plugin's skills/agents/hooks/commands. Use Option 1 instead if you want full plugin features.

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

## Why upgrade to HTTP mode?

Stdio mode is the default and works for most personal/single-user scenarios. Consider switching to HTTP mode (Option 3) when you need:

- **claude.ai web compatibility** -- HTTP transport is required to connect plugins to claude.ai web client (stdio only works with desktop clients)
- **One server shared across N Claude Code sessions** -- single daemon serves all sessions instead of spawning a fresh stdio process per session (lower memory, shared cache)
- **Browser-based GDrive OAuth flow** -- HTTP mode performs the Google Device Code flow via the bundled public client; no manual `GOOGLE_DRIVE_CLIENT_ID` setup required
- **Multi-device credential sync** -- self-host the HTTP server once, log in from multiple machines without re-pasting API keys
- **Multi-user team sharing** -- single self-hosted instance supports N users with per-JWT-sub credential isolation
- **Always-on persistent process** -- ideal for webhooks, scheduled agents, or background automation

## Option 3: Docker HTTP (recommended)

> **⚠️ Before adding the HTTP override below, ensure this plugin is NOT installed via marketplace**: Run `/plugin uninstall wet-mcp@n24q02m-plugins` first if you previously ran `/plugin install`. Otherwise both entries (plugin's stdio + your HTTP override) will load simultaneously since plugin matches by endpoint, not name.
>
> **Trade-off accepted**: Choosing this method means you lose this plugin's skills/agents/hooks/commands. For example, the `wet-mcp:fact-check` skill will no longer be available. Use Option 1 instead if you want full plugin features.

> **Switching transport vs. setting credentials**: The `userConfig` prompt only configures credentials for stdio mode (Method 1 / Option 1). To switch transport to HTTP, override `mcpServers` in your client settings per the snippets below -- this is a separate path from `userConfig` and is not driven by the install prompt.

### 3.2. Self-host with docker-compose

HTTP mode runs as a persistent multi-user server with browser-based credential setup. GDrive OAuth uses a **bundled public Google Desktop client** (`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`) per Google's official Desktop OAuth pattern -- no user-side OAuth registration is required. Users authenticate via the device-code flow in their browser.

```bash
docker run -d --name wet-mcp-http \
  -p 8084:8084 \
  -v wet-data:/data \
  -e MCP_TRANSPORT=http \
  -e PUBLIC_URL=https://wet.example.com \
  -e MCP_DCR_SERVER_SECRET=your-random-secret \
  n24q02m/wet-mcp:latest
```

Configure MCP client to connect:

```json
{
  "mcpServers": {
    "wet": {
      "url": "https://wet.example.com/mcp"
    }
  }
}
```

On first call, the client redirects to the relay form. Fill in API keys (all optional) and -- if `SYNC_ENABLED=true` -- complete the GDrive device-code flow in your browser using the bundled public client. Each user receives an isolated credential vault keyed by JWT sub.

### Edge auth: relay password

Public HTTP deployments expose `<your-domain>/authorize` to URL discovery. To prevent random Internet users from accessing the relay form, mint a relay password:

```bash
openssl rand -hex 32
# Save in your skret / .env as:
MCP_RELAY_PASSWORD=<generated-32-byte-hex>
```

Share this password out-of-band (Signal/email/SMS) with anyone you invite to use your server. They will see a login form when first opening `/authorize`; once logged in, the cookie persists 24 hours.

**Single-user dev exception**: If `PUBLIC_URL=http://localhost:8080`, you can leave `MCP_RELAY_PASSWORD` empty to disable the gate. The server logs a warning if you skip the password with a non-localhost `PUBLIC_URL`.

## Environment Variables

All environment variables are **optional**. The server works in local mode (ONNX embedding + SearXNG) with zero configuration.

### API Keys (Cloud Providers)

| Variable | Required | Default | Description |
|:---------|:---------|:--------|:------------|
| `JINA_AI_API_KEY` | No | -- | Jina AI key: search + extraction + embedding + reranking (highest priority) |
| `GEMINI_API_KEY` | No | -- | Google Gemini key: LLM (structured extraction, media analysis) + embedding |
| `OPENAI_API_KEY` | No | -- | OpenAI key: LLM + embedding (lower priority than Gemini) |
| `COHERE_API_KEY` | No | -- | Cohere key: embedding + reranking |
| `BRAVE_API_KEY` | No | -- | Brave Search API key (premium search provider) |
| `SERPER_API_KEY` | No | -- | Serper search API key (premium search provider) |
| `GITHUB_TOKEN` | No | auto-detect | GitHub token for docs discovery (60 -> 5000 req/hr). Auto-detected from `gh auth token` |

### Embedding and Reranking

| Variable | Required | Default | Description |
|:---------|:---------|:--------|:------------|
| `EMBEDDING_BACKEND` | No | auto-detect | `cloud` or `local` (Qwen3). Auto: API keys present -> cloud, else local |
| `EMBEDDING_MODEL` | No | auto-detect | Cloud embedding model name |
| `EMBEDDING_DIMS` | No | `0` (auto=768) | Embedding dimensions |
| `RERANK_ENABLED` | No | `true` | Enable reranking after search |
| `RERANK_BACKEND` | No | auto-detect | `cloud` or `local`. Auto: Cohere/Jina key -> cloud, else local |
| `RERANK_MODEL` | No | auto-detect | Cloud rerank model name |
| `RERANK_TOP_N` | No | `10` | Return top N results after reranking |

### LLM

| Variable | Required | Default | Description |
|:---------|:---------|:--------|:------------|
| `LLM_MODELS` | No | auto-detect | LLM model for media analysis (LiteLLM format) |

### SearXNG

| Variable | Required | Default | Description |
|:---------|:---------|:--------|:------------|
| `WET_AUTO_SEARXNG` | No | `true` | Auto-start embedded SearXNG subprocess |
| `WET_SEARXNG_PORT` | No | `41592` | SearXNG port |
| `SEARXNG_URL` | No | `http://localhost:41592` | External SearXNG URL (when auto disabled) |
| `SEARXNG_TIMEOUT` | No | `30` | SearXNG request timeout in seconds |

### File Conversion

| Variable | Required | Default | Description |
|:---------|:---------|:--------|:------------|
| `CONVERT_MAX_FILE_SIZE` | No | `104857600` | Max file size for local conversion in bytes (100MB) |
| `CONVERT_ALLOWED_DIRS` | No | -- | Comma-separated paths to restrict local file conversion |

### Storage and Cache

| Variable | Required | Default | Description |
|:---------|:---------|:--------|:------------|
| `CACHE_DIR` | No | `~/.wet-mcp` | Data directory for cache, docs, downloads |
| `DOCS_DB_PATH` | No | `~/.wet-mcp/docs.db` | Docs database location |
| `DOWNLOAD_DIR` | No | `~/.wet-mcp/downloads` | Media download directory |
| `TOOL_TIMEOUT` | No | `120` | Tool execution timeout in seconds (0=no timeout) |
| `WET_CACHE` | No | `true` | Enable/disable web cache |

### Google Drive Sync

| Variable | Required | Default | Description |
|:---------|:---------|:--------|:------------|
| `SYNC_ENABLED` | No | `false` | Enable Google Drive sync |
| `GOOGLE_DRIVE_CLIENT_ID` | No | bundled public client | OAuth client ID. HTTP mode auto-uses bundled public Desktop client |
| `GOOGLE_DRIVE_CLIENT_SECRET` | No | bundled public secret | OAuth client secret (Desktop public client per Google docs) |
| `SYNC_FOLDER` | No | `wet-mcp` | Google Drive folder name |
| `SYNC_INTERVAL` | No | `300` | Auto-sync interval in seconds (0=manual) |

### General

| Variable | Required | Default | Description |
|:---------|:---------|:--------|:------------|
| `LOG_LEVEL` | No | `INFO` | Logging level |
| `MCP_TRANSPORT` | No | `stdio` | Transport: `stdio` (default) or `http` |
| `PUBLIC_URL` | No | -- | HTTP mode: public URL of the server (required for multi-user OAuth) |
| `MCP_DCR_SERVER_SECRET` | No | -- | HTTP mode: random secret for Dynamic Client Registration JWT signing |

## Authentication

### Stdio Mode (default)

Set API keys directly as environment variables. Basic SearXNG search works without any env. Advanced features (cloud embedding, Gemini LLM, premium search) activate when corresponding keys are set. Credentials live only in the local process environment.

### HTTP Mode (optional, multi-user)

After connecting an MCP client to the HTTP endpoint, the client redirects to the relay form on first call:

1. Open the relay URL in any browser
2. Fill in API keys on the guided form (all optional)
3. If `SYNC_ENABLED=true`, complete the GDrive device-code flow using the bundled public Desktop client (no user OAuth registration needed)
4. Credentials are encrypted per-JWT-sub and isolated per user

Each user receives an isolated credential vault keyed by JWT sub.

## Verification

After setup, verify the server is working by calling the `search` tool:

```
search(action="search", query="test query", limit=3)
```

Expected: returns search results with titles, URLs, and snippets.
