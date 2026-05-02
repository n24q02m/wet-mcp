# WET (Web Extended Toolkit) -- Manual Setup Guide

> **2026-05-02 Update (v&lt;auto&gt;+)**: Plugin install (Method 1) uses stdio mode. Basic SearXNG search works without env; advanced features (GDrive sync, Brave, Serper, Gemini) need optional env vars OR HTTP mode for OAuth flows.
> The previous "Zero-Config Relay" auto-spawn pattern has been removed.

## Prerequisites

- **Python 3.13** (3.14+ is NOT supported due to SearXNG incompatibility)
- `uv` or `uvx` installed ([docs](https://docs.astral.sh/uv/getting-started/installation/))
- Docker (optional, for containerized setup)

## Method 1: Plugin Install (stdio default)

For Claude Code users, the plugin approach is the simplest. Plugin install uses **stdio mode** -- basic SearXNG web search works **without any env vars**. Advanced features require optional API keys.

1. Open Claude Code
2. Run the following commands:
   ```bash
   /plugin marketplace add n24q02m/claude-plugins
   /plugin install wet-mcp@n24q02m-plugins
   ```
3. (Optional) Set env vars for advanced features in `~/.claude/settings.local.json`:
   ```json
   {
     "mcpServers": {
       "wet-mcp": {
         "env": {
           "BRAVE_API_KEY": "your-brave-key",
           "SERPER_API_KEY": "your-serper-key",
           "GEMINI_API_KEY": "AIza..."
         }
       }
     }
   }
   ```
4. Restart Claude Code -- the server starts automatically when CC launches

Without env vars: basic SearXNG metasearch, content extraction, library docs, ONNX local embedding/reranking all work. With env vars: cloud embedding/reranking (faster), Gemini LLM analysis, premium search providers.

## Method 2: uvx Direct (stdio)

1. Add to your MCP client configuration file:

   **Claude Code** (`~/.claude/settings.local.json`):
   ```json
   {
     "mcpServers": {
       "wet": {
         "command": "uvx",
         "args": ["--python", "3.13", "wet-mcp"],
         "env": {
           "BRAVE_API_KEY": "your-brave-key",
           "GEMINI_API_KEY": "AIza..."
         }
       }
     }
   }
   ```

   **Codex CLI** (`~/.codex/config.toml`):
   ```toml
   [mcp_servers.wet]
   command = "uvx"
   args = ["--python", "3.13", "wet-mcp"]
   [mcp_servers.wet.env]
   BRAVE_API_KEY = "your-brave-key"
   GEMINI_API_KEY = "AIza..."
   ```

   **OpenCode** (`opencode.json` in project root):
   ```json
   {
     "mcpServers": {
       "wet": {
         "command": "uvx",
         "args": ["--python", "3.13", "wet-mcp"],
         "env": {
           "BRAVE_API_KEY": "your-brave-key",
           "GEMINI_API_KEY": "AIza..."
         }
       }
     }
   }
   ```

2. Restart your MCP client
3. On first run, the server auto-installs SearXNG, Playwright chromium, and downloads embedding models (~1.1GB)

All env vars are optional. Without any env, basic SearXNG search + ONNX local embedding still work.

## Method 3: Docker (stdio)

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

## Method 4: Build from Source

1. Clone the repository:
   ```bash
   git clone https://github.com/n24q02m/wet-mcp.git
   cd wet-mcp
   ```

2. Install dependencies:
   ```bash
   uv sync
   ```

3. Run the server:
   ```bash
   uv run wet-mcp
   ```

## Why upgrade to HTTP mode?

Stdio mode is the default and works for most personal/single-user scenarios. Consider switching to HTTP mode (Method 5) when you need:

- **claude.ai web compatibility** -- HTTP transport is required to connect plugins to claude.ai web client (stdio only works with desktop clients)
- **One server shared across N Claude Code sessions** -- single daemon serves all sessions instead of spawning a fresh stdio process per session (lower memory, shared cache)
- **Browser-based GDrive OAuth flow** -- HTTP mode performs the Google Device Code flow via the bundled public client; no manual `GOOGLE_DRIVE_CLIENT_ID` setup required
- **Multi-device credential sync** -- self-host the HTTP server once, log in from multiple machines without re-pasting API keys
- **Multi-user team sharing** -- single self-hosted instance supports N users with per-JWT-sub credential isolation
- **Always-on persistent process** -- ideal for webhooks, scheduled agents, or background automation

## Method 5: Self-Host HTTP Mode (multi-user)

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
