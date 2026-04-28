# WET (Web Extended Toolkit) -- Manual Setup Guide

## Prerequisites

- **Python 3.13** (3.14+ is NOT supported due to SearXNG incompatibility)
- `uv` or `uvx` installed ([docs](https://docs.astral.sh/uv/getting-started/installation/))
- Docker (optional, for containerized setup)

## Method 1: Plugin Install

For Claude Code users, the plugin approach is the simplest.

1. Open Claude Code
2. Run the following commands:
   ```bash
   /plugin marketplace add n24q02m/claude-plugins
   /plugin install wet-mcp@n24q02m-plugins
   ```
3. The server starts automatically when Claude Code launches
4. On first run, a relay setup URL appears -- open it to configure API keys (optional)

## Method 2: uvx Direct

1. Add to your MCP client configuration file:

   **Claude Code** (`~/.claude/settings.local.json`):
   ```json
   {
     "mcpServers": {
       "wet": {
         "command": "uvx",
         "args": ["--python", "3.13", "wet-mcp"]
       }
     }
   }
   ```

   **Codex CLI** (`~/.codex/config.toml`):
   ```toml
   [mcp_servers.wet]
   command = "uvx"
   args = ["--python", "3.13", "wet-mcp"]
   ```

   **OpenCode** (`opencode.json` in project root):
   ```json
   {
     "mcpServers": {
       "wet": {
         "command": "uvx",
         "args": ["--python", "3.13", "wet-mcp"]
       }
     }
   }
   ```

2. Restart your MCP client
3. On first run, the server auto-installs SearXNG, Playwright chromium, and downloads embedding models (~1.1GB)
4. A relay setup URL appears in stderr -- open it to configure cloud API keys (optional)

## Method 3: Docker

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

## Credential Setup

### Option A: Environment Variables (Recommended)

Set API keys in your shell profile or MCP client settings:

```bash
export JINA_AI_API_KEY="jina_..."
export GEMINI_API_KEY="AIza..."
export GITHUB_TOKEN="ghp_..."
```

When environment variables are set, the relay is skipped entirely.

### Option B: Zero-Config Relay

> **Recommended for new users.** The relay is the primary setup method -- no environment variables needed. Credentials are encrypted end-to-end and stored locally.

No manual configuration needed. On first start:

1. The server prints a setup URL to stderr (e.g., `http://127.0.0.1:<port>/authorize`). The port is allocated dynamically on each start, and `wet-mcp` runs the relay locally by default — no public n24q02m.com subdomain is provisioned for wet/mnemo/crg/imagine. To run a self-hosted remote relay, set `MCP_RELAY_URL=https://your-host/...`.
2. Open the URL in any browser
3. Fill in your API keys on the guided form:
   - **Jina AI API Key** -- enables search, extraction, embedding, reranking ([get key](https://jina.ai/api-key))
   - **Gemini API Key** -- enables LLM and embedding, free tier available ([get key](https://aistudio.google.com/apikey))
   - **OpenAI API Key** -- enables LLM and embedding ([get key](https://platform.openai.com/api-keys))
   - **Cohere API Key** -- enables embedding and reranking ([get key](https://dashboard.cohere.com/api-keys))
4. All fields are optional -- leave empty for pure local mode
5. Credentials are encrypted and stored at `~/.config/mcp/config.enc`

### Google Drive Sync Setup (Optional)

To sync indexed docs across machines:

1. Set environment variables:
   ```bash
   export SYNC_ENABLED=true
   export GOOGLE_DRIVE_CLIENT_ID="your-client-id.apps.googleusercontent.com"
   export GOOGLE_DRIVE_CLIENT_SECRET="your-client-secret"
   ```

2. Call the setup tool:
   ```
   setup(action="setup_sync")
   ```

3. Visit the URL displayed and enter the device code
4. OAuth token is saved at `~/.wet-mcp/tokens/google_drive.json` (600 permissions)

## Environment Variable Reference

All environment variables are **optional**. See [docs/setup-with-agent.md](setup-with-agent.md#environment-variables) for the complete table.

### Key Variables

| Variable | Default | Description |
|:---------|:--------|:------------|
| `JINA_AI_API_KEY` | -- | Jina AI: search + extraction + embedding + reranking |
| `GEMINI_API_KEY` | -- | Gemini: LLM + embedding (free tier) |
| `OPENAI_API_KEY` | -- | OpenAI: LLM + embedding |
| `COHERE_API_KEY` | -- | Cohere: embedding + reranking |
| `GITHUB_TOKEN` | auto-detect | GitHub token for docs discovery |
| `WET_AUTO_SEARXNG` | `true` | Auto-start embedded SearXNG |
| `SYNC_ENABLED` | `false` | Enable Google Drive sync |
| `LOG_LEVEL` | `INFO` | Logging level |

### Provider Priority

- **Embedding**: Jina AI > Gemini > OpenAI > Cohere > Local ONNX (Qwen3)
- **Reranking**: Jina AI > Cohere > Local ONNX (Qwen3)
- **LLM**: Gemini > OpenAI > Disabled
- **Search**: Jina AI > SearXNG (always available locally)

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

### Relay setup URL does not appear

The relay URL only appears when no API keys are set in environment. If you have any of `JINA_AI_API_KEY`, `GEMINI_API_KEY`, `OPENAI_API_KEY`, or `COHERE_API_KEY` set, the relay is skipped.

To force relay setup, use the MCP tool: `setup(action="setup_relay")`

### Docker volume permissions

If you encounter permission errors with the Docker volume:

```bash
docker run -i --rm -v wet-data:/data --user $(id -u):$(id -g) n24q02m/wet-mcp:latest
```

### Embedding model download fails

If ONNX model download fails behind a proxy, use cloud embedding instead by setting any API key (e.g., `GEMINI_API_KEY`).
