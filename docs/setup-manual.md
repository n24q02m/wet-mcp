# WET (Web Extended Toolkit) -- Manual Setup Guide

> **2026-05-02 Update (v&lt;auto&gt;+)**: Plugin install (Method 1) uses stdio mode. Basic SearXNG search works without env; advanced features (GDrive sync, Brave, Serper, Gemini) need optional env vars OR HTTP mode for OAuth flows.
> The previous "Zero-Config Relay" auto-spawn pattern has been removed.

## Method overview

This plugin supports 3 install methods. Pick the one that matches your use case:

| Priority | Method | Transport | Best for |
|---|---|---|---|
| **1. Default** | Plugin install (`uvx`/`npx`) | stdio | Quick local start, single workstation, no OAuth/HTTP needed. |
| **2. Fallback** | Docker stdio (`docker run -i --rm`) | stdio | Windows/macOS where native uvx/npx hits PATH or Python version issues. |
| **3. Recommended** | Docker HTTP (`docker run -p 8080:8080`) | HTTP | Multi-device, OAuth/relay-form auth, team self-host, claude.ai web compatibility. |

All MCP servers across this stack share this priority hierarchy. Note: 2 plugins (`better-godot-mcp` and `better-code-review-graph`) only support Method 1 (stdio) -- they need direct host access to project files / repo paths and don't ship Docker / HTTP variants.

> **⚠️ Mutually exclusive — pick ONE per plugin**: If you choose Method 2 (Docker stdio override) OR Method 3 (HTTP), do NOT also `/plugin install` this plugin via marketplace. Both load simultaneously and create duplicate entries in `/mcp` dialog (plugin's stdio + your override). Plugin matching is by **endpoint** (URL or command string) per CC docs, not by name — and `npx`/`uvx` ≠ `docker` ≠ HTTP URL, so all three are distinct endpoints. Trade-off: choosing Method 2 or Method 3 means you lose this plugin's skills/agents/hooks/commands. For full plugin features, use Method 1 (default plugin install) with `userConfig` credentials prompted at install time.

## Prerequisites

- **Python 3.13** (3.14+ is NOT supported due to SearXNG incompatibility)
- `uv` or `uvx` installed ([docs](https://docs.astral.sh/uv/getting-started/installation/))
- Docker (optional, for containerized setup)

## Method 1: Plugin Install (stdio default)

For Claude Code users, the plugin approach is the simplest. Plugin install uses **stdio mode** -- basic SearXNG web search works **without any env vars**. Advanced features require optional API keys.

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

1. Open Claude Code.
2. Install the plugin (Claude Code prompts for `JINA_AI_API_KEY` + `GEMINI_API_KEY` -- press Enter to skip):
   ```bash
   /plugin marketplace add n24q02m/claude-plugins
   /plugin install wet-mcp@n24q02m-plugins
   ```
3. Restart Claude Code -- the server starts automatically when CC launches with the values injected.

Without env vars: basic SearXNG metasearch, content extraction, library docs, ONNX local embedding/reranking all work. With env vars: cloud embedding/reranking (faster), Gemini LLM analysis, premium search providers.

> **Note**: This installs the full plugin (skills + agents + hooks + commands + stdio MCP server). If you'd rather use Method 2 (Docker stdio) or Method 3 (HTTP) below, DO NOT `/plugin install` this plugin — pick Method 2 or Method 3 instead. All three methods are mutually exclusive (see Method overview).

## Method 2: Docker stdio (fallback)

> **⚠️ Before adding the Docker stdio override below, ensure this plugin is NOT installed via marketplace**: Run `/plugin uninstall wet-mcp@n24q02m-plugins` first if you previously ran `/plugin install`. Otherwise both entries (plugin's `npx`/`uvx` stdio + your `docker run` stdio) will load simultaneously since plugin matches by endpoint (command string), not by name.
>
> **Trade-off accepted**: Choosing this method means you lose this plugin's skills/agents/hooks/commands. Use Method 1 instead if you want full plugin features.

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

Stdio mode is the default and works for most personal/single-user scenarios. Consider switching to HTTP mode (Method 3 self-host) when you need:

- **claude.ai web compatibility** -- HTTP transport is required to connect plugins to claude.ai web client (stdio only works with desktop clients)
- **One server shared across N Claude Code sessions** -- single daemon serves all sessions instead of spawning a fresh stdio process per session (lower memory, shared cache)
- **Browser-based GDrive OAuth flow** -- HTTP mode performs the Google Device Code flow via the bundled public client; no manual `GOOGLE_DRIVE_CLIENT_ID` setup required
- **Multi-device credential sync** -- self-host the HTTP server once, log in from multiple machines without re-pasting API keys
- **Multi-user team sharing** -- single self-hosted instance supports N users with per-JWT-sub credential isolation
- **Always-on persistent process** -- ideal for webhooks, scheduled agents, or background automation

## Method 3: Docker HTTP (recommended)

> **⚠️ Before adding the HTTP override below, ensure this plugin is NOT installed via marketplace**: Run `/plugin uninstall wet-mcp@n24q02m-plugins` first if you previously ran `/plugin install`. Otherwise both entries (plugin's stdio + your HTTP override) will load simultaneously since plugin matches by endpoint, not name.
>
> **Trade-off accepted**: Choosing this method means you lose this plugin's skills/agents/hooks/commands. For example, the `wet-mcp:fact-check` skill will no longer be available. Use Method 1 instead if you want full plugin features.

> **Switching transport vs. setting credentials**: The `userConfig` prompt only configures credentials for stdio mode (Method 1 / Option 1). To switch transport to HTTP, override `mcpServers` in your client settings per the snippets below -- this is a separate path from `userConfig` and is not driven by the install prompt.

### 3.2. Self-host with docker-compose

HTTP mode runs as a persistent multi-user server with browser-based credential setup. GDrive OAuth uses a **bundled public Google Desktop client** (`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`) per Google's official Desktop OAuth pattern -- no user-side OAuth registration is required. Users authenticate via the device-code flow in their browser.

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

3. On first call, the client redirects to the relay form. Fill in API keys (all optional) and -- if `SYNC_ENABLED=true` -- complete the GDrive device-code flow in your browser using the bundled public client.

Each user receives an isolated credential vault keyed by JWT sub. No per-user OAuth registration needed.

### Edge auth: relay password

Public HTTP deployments expose `<your-domain>/authorize` to URL discovery. To prevent random Internet users from accessing the relay form, mint a relay password:

```bash
openssl rand -hex 32
# Save in your skret / .env as:
MCP_RELAY_PASSWORD=<generated-32-byte-hex>
```

Share this password out-of-band (Signal/email/SMS) with anyone you invite to use your server. They will see a login form when first opening `/authorize`; once logged in, the cookie persists 24 hours.

**Single-user dev exception**: If `PUBLIC_URL=http://localhost:8080`, you can leave `MCP_RELAY_PASSWORD` empty to disable the gate. The server logs a warning if you skip the password with a non-localhost `PUBLIC_URL`.

## Troubleshooting

### Server fails to start with Python 3.14+

wet-mcp requires Python 3.13 due to SearXNG incompatibility. Always use `--python 3.13` with uvx:

```bash
uvx --python 3.13 wet-mcp
```

### First run takes a long time

On first start, the server downloads:
- SearXNG search engine
- Playwright chromium browser
- ONNX embedding and reranker models (~1.1GB total)

Use the warmup command to pre-download: `setup(action="warmup")`

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

If ONNX model download fails behind a proxy, use cloud embedding instead by setting any API key (e.g., `GEMINI_API_KEY`).

## Environment Variable Reference

All environment variables are **optional**. See [docs/setup-with-agent.md](setup-with-agent.md#environment-variables) for the complete table.

### Key Variables

| Variable | Default | Description |
|:---------|:--------|:------------|
| `JINA_AI_API_KEY` | -- | Jina AI: search + extraction + embedding + reranking |
| `GEMINI_API_KEY` | -- | Gemini: LLM + embedding (free tier) |
| `OPENAI_API_KEY` | -- | OpenAI: LLM + embedding |
| `COHERE_API_KEY` | -- | Cohere: embedding + reranking |
| `BRAVE_API_KEY` | -- | Brave Search API key (premium search) |
| `SERPER_API_KEY` | -- | Serper search API key (premium search) |
| `GITHUB_TOKEN` | auto-detect | GitHub token for docs discovery |
| `WET_AUTO_SEARXNG` | `true` | Auto-start embedded SearXNG |
| `SYNC_ENABLED` | `false` | Enable Google Drive sync |
| `LOG_LEVEL` | `INFO` | Logging level |

### Provider Priority

- **Embedding**: Jina AI > Gemini > OpenAI > Cohere > Local ONNX (Qwen3)
- **Reranking**: Jina AI > Cohere > Local ONNX (Qwen3)
- **LLM**: Gemini > OpenAI > Disabled
- **Search**: Brave > Serper > Jina AI > SearXNG (always available locally)
