# WET (Web Extended Toolkit) -- Agent Setup Guide

> Give this file to your AI agent to automatically set up wet-mcp.

## Option 1: Claude Code Plugin (Recommended)

```bash
# Install from marketplace (includes skills: /fact-check, /compare)
/plugin marketplace add n24q02m/claude-plugins
/plugin install wet-mcp@n24q02m-plugins
```

No further configuration needed. The server auto-configures via relay on first run.

## Option 2: MCP Direct

**Python 3.13 required** -- Python 3.14+ is NOT supported due to SearXNG incompatibility.

### Claude Code (settings.json)

Add to `~/.claude/settings.local.json` under `"mcpServers"`:

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

### Codex CLI (config.toml)

Add to `~/.codex/config.toml`:

```toml
[mcp_servers.wet]
command = "uvx"
args = ["--python", "3.13", "wet-mcp"]
```

### OpenCode (opencode.json)

Add to `opencode.json` in the project root:

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

## Option 3: Docker

```bash
docker run -i --rm \
  --name mcp-wet \
  -v wet-data:/data \
  -e JINA_AI_API_KEY \
  -e GEMINI_API_KEY \
  -e OPENAI_API_KEY \
  -e COHERE_API_KEY \
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

## Environment Variables

All environment variables are **optional**. The server works in local mode (ONNX embedding + SearXNG) with zero configuration.

### API Keys (Cloud Providers)

| Variable | Required | Default | Description |
|:---------|:---------|:--------|:------------|
| `JINA_AI_API_KEY` | No | -- | Jina AI key: search + extraction + embedding + reranking (highest priority) |
| `GEMINI_API_KEY` | No | -- | Google Gemini key: LLM (structured extraction, media analysis) + embedding |
| `OPENAI_API_KEY` | No | -- | OpenAI key: LLM + embedding (lower priority than Gemini) |
| `COHERE_API_KEY` | No | -- | Cohere key: embedding + reranking |
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
| `LLM_MODELS` | No | `gemini-3-flash-preview` | LLM model for media analysis (google-genai or openai format) |

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
| `GOOGLE_DRIVE_CLIENT_ID` | No | -- | OAuth client ID (required for sync) |
| `GOOGLE_DRIVE_CLIENT_SECRET` | No | -- | OAuth client secret (required for sync) |
| `SYNC_FOLDER` | No | `wet-mcp` | Google Drive folder name |
| `SYNC_INTERVAL` | No | `300` | Auto-sync interval in seconds (0=manual) |

### General

| Variable | Required | Default | Description |
|:---------|:---------|:--------|:------------|
| `LOG_LEVEL` | No | `INFO` | Logging level |
| `MCP_RELAY_URL` | No | `https://wet-mcp.n24q02m.com` | Relay server URL for zero-config setup |

## Authentication

### Zero-Config Relay (Default)

On first run without any API keys in environment:

1. Server starts and creates a relay session
2. A setup URL is printed to stderr
3. Open the URL in any browser
4. Fill in API keys on the guided form (all optional)
5. Credentials are encrypted and stored locally at `~/.config/mcp/config.enc`
6. Subsequent runs load saved credentials automatically

The relay form has 4 optional fields:
- **Jina AI API Key** -- search + extraction + embedding + reranking
- **Gemini API Key** -- LLM + embedding (free tier available)
- **OpenAI API Key** -- LLM + embedding
- **Cohere API Key** -- embedding + reranking

Leave all empty to use pure local mode (ONNX models + SearXNG).

### Google Drive Sync (Optional)

After relay setup, if `GOOGLE_DRIVE_CLIENT_ID` is configured, the server starts OAuth Device Code flow:

1. A URL and code are displayed
2. Visit the URL and enter the code
3. OAuth token is saved at `~/.wet-mcp/tokens/google_drive.json`

### Environment Variables (CI/Automation)

Set API keys directly as environment variables to skip relay entirely.

## Verification

After setup, verify the server is working by calling the `search` tool:

```
search(action="search", query="test query", limit=3)
```

Expected: returns search results with titles, URLs, and snippets.
