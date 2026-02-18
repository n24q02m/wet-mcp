# WET - Web Extended Toolkit MCP Server

**Open-source MCP Server for web search, content extraction, library docs & multimodal analysis.**

[![PyPI](https://img.shields.io/pypi/v/wet-mcp)](https://pypi.org/project/wet-mcp/)
[![Docker](https://img.shields.io/docker/v/n24q02m/wet-mcp?label=docker)](https://hub.docker.com/r/n24q02m/wet-mcp)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

## Features

- **Web Search** - Search via embedded SearXNG (metasearch: Google, Bing, DuckDuckGo, Brave)
- **Academic Research** - Search Google Scholar, Semantic Scholar, arXiv, PubMed, CrossRef, BASE
- **Library Docs** - Auto-discover and index documentation with FTS5 hybrid search
- **Content Extract** - Extract clean content (Markdown/Text)
- **Deep Crawl** - Crawl multiple pages from a root URL with depth control
- **Site Map** - Discover website URL structure
- **Media** - List and download images, videos, audio files
- **Anti-bot** - Stealth mode bypasses Cloudflare, Medium, LinkedIn, Twitter
- **Local Cache** - TTL-based caching for all web operations
- **Docs Sync** - Sync indexed docs across machines via rclone

---

## Quick Start

### Prerequisites

- **Python 3.13** (required -- Python 3.14+ is **not** supported due to SearXNG incompatibility)

> **Warning:** You **must** specify `--python 3.13` when using `uvx`. Without it, `uvx` may pick Python 3.14+ which causes SearXNG search to fail silently.

**On first run**, the server automatically installs SearXNG, Playwright chromium, and starts the embedded search engine.

### Option 1: Minimal uvx (Recommended)

```jsonc
{
  "mcpServers": {
    "wet": {
      "command": "uvx",
      "args": ["--python", "3.13", "wet-mcp@latest"]
      // No API keys needed -- local Qwen3-Embedding-0.6B + Qwen3-Reranker-0.6B (ONNX, CPU)
      // First run downloads ~570MB model, cached for subsequent runs
    }
  }
}
```

### Option 2: Minimal Docker

```jsonc
{
  "mcpServers": {
    "wet": {
      "command": "docker",
      "args": [
        "run", "-i", "--rm",
        "--name", "mcp-wet",
        "-v", "wet-data:/data",
        "n24q02m/wet-mcp:latest"
      ]
      // Volume persists cached web pages, indexed docs, and downloads
      // Same built-in local embedding + reranking as uvx
    }
  }
}
```

### Option 3: Full uvx

```jsonc
{
  "mcpServers": {
    "wet": {
      "command": "uvx",
      "args": ["--python", "3.13", "wet-mcp@latest"],
      "env": {
        "API_KEYS": "GOOGLE_API_KEY:AIza...",     // cloud embedding (Gemini > OpenAI > Mistral > Cohere) + media analysis
        // Reranking: auto local Qwen3-Reranker-0.6B. Or set RERANK_MODEL=cohere/rerank-v3.5 for cloud reranking
        "GITHUB_TOKEN": "ghp_...",                 // higher rate limits for docs discovery
        "SYNC_ENABLED": "true",                    // enable docs sync
        "SYNC_REMOTE": "gdrive",                   // rclone remote name
        "SYNC_INTERVAL": "300",                    // auto-sync every 5min (0 = manual)
        "RCLONE_CONFIG_GDRIVE_TYPE": "drive",
        "RCLONE_CONFIG_GDRIVE_TOKEN": "<base64>"   // from: uvx --python 3.13 wet-mcp setup-sync drive
      }
    }
  }
}
```

### Option 4: Full Docker

```jsonc
{
  "mcpServers": {
    "wet": {
      "command": "docker",
      "args": [
        "run", "-i", "--rm",
        "--name", "mcp-wet",
        "-v", "wet-data:/data",
        "-e", "API_KEYS",
        "-e", "GITHUB_TOKEN",
        "-e", "SYNC_ENABLED",
        "-e", "SYNC_REMOTE",
        "-e", "SYNC_INTERVAL",
        "-e", "RCLONE_CONFIG_GDRIVE_TYPE",
        "-e", "RCLONE_CONFIG_GDRIVE_TOKEN",
        "n24q02m/wet-mcp:latest"
      ],
      "env": {
        "API_KEYS": "GOOGLE_API_KEY:AIza...",
        "GITHUB_TOKEN": "ghp_...",
        "SYNC_ENABLED": "true",
        "SYNC_REMOTE": "gdrive",
        "SYNC_INTERVAL": "300",
        "RCLONE_CONFIG_GDRIVE_TYPE": "drive",
        "RCLONE_CONFIG_GDRIVE_TOKEN": "<base64>"
      }
      // Same auto-detection: cloud embedding from API_KEYS, auto local reranking
    }
  }
}
```

### Sync setup (one-time)

```bash
# Google Drive
uvx --python 3.13 wet-mcp setup-sync drive

# Other providers (any rclone remote type)
uvx --python 3.13 wet-mcp setup-sync dropbox
uvx --python 3.13 wet-mcp setup-sync onedrive
uvx --python 3.13 wet-mcp setup-sync s3
```

Opens a browser for OAuth and outputs env vars (`RCLONE_CONFIG_*`) to set. Both raw JSON and base64 tokens are supported.

---

## Tools

| Tool | Actions | Description |
|:-----|:--------|:------------|
| `search` | search, research, docs | Web search, academic research, library documentation |
| `extract` | extract, crawl, map | Content extraction, deep crawling, site mapping |
| `media` | list, download, analyze | Media discovery & download |
| `config` | status, set, cache_clear, docs_reindex | Server configuration and cache management |
| `help` | - | Full documentation for any tool |

### Usage Examples

```json
// search tool
{"action": "search", "query": "python web scraping", "max_results": 10}
{"action": "research", "query": "transformer attention mechanism"}
{"action": "docs", "query": "how to create routes", "library": "fastapi"}
{"action": "docs", "query": "dependency injection", "library": "spring-boot", "language": "java"}

// extract tool
{"action": "extract", "urls": ["https://example.com"]}
{"action": "crawl", "urls": ["https://docs.python.org"], "depth": 2}
{"action": "map", "urls": ["https://example.com"]}

// media tool
{"action": "list", "url": "https://github.com/python/cpython"}
{"action": "download", "media_urls": ["https://example.com/image.png"]}
```

---

## Configuration

| Variable | Default | Description |
|:---------|:--------|:------------|
| `WET_AUTO_SEARXNG` | `true` | Auto-start embedded SearXNG subprocess |
| `WET_SEARXNG_PORT` | `41592` | SearXNG port (optional) |
| `SEARXNG_URL` | `http://localhost:41592` | External SearXNG URL (optional, when auto disabled) |
| `SEARXNG_TIMEOUT` | `30` | SearXNG request timeout in seconds (optional) |
| `API_KEYS` | - | LLM API keys (optional, format: `ENV_VAR:key,...`) |
| `LLM_MODELS` | `gemini/gemini-3-flash-preview` | LiteLLM model for media analysis (optional) |
| `EMBEDDING_BACKEND` | (auto-detect) | `litellm` (cloud API) or `local` (Qwen3 ONNX). Auto: litellm > local > FTS5-only |
| `EMBEDDING_MODEL` | (auto-detect) | LiteLLM embedding model (optional) |
| `EMBEDDING_DIMS` | `0` (auto=768) | Embedding dimensions (optional) |
| `RERANK_ENABLED` | `true` | Enable reranking after search (auto-disabled if no backend) |
| `RERANK_BACKEND` | (auto-detect) | `litellm` or `local`. Auto: litellm (if RERANK_MODEL) > local |
| `RERANK_MODEL` | - | LiteLLM rerank model, e.g. `cohere/rerank-v3.5` (optional, enables cloud reranking) |
| `RERANK_TOP_N` | `10` | Return top N results after reranking |
| `CACHE_DIR` | `~/.wet-mcp` | Data directory for cache DB, docs DB, downloads (optional) |
| `DOCS_DB_PATH` | `~/.wet-mcp/docs.db` | Docs database location (optional) |
| `DOWNLOAD_DIR` | `~/.wet-mcp/downloads` | Media download directory (optional) |
| `TOOL_TIMEOUT` | `120` | Tool execution timeout in seconds, 0=no timeout (optional) |
| `WET_CACHE` | `true` | Enable/disable web cache (optional) |
| `GITHUB_TOKEN` | - | GitHub personal access token for library discovery (optional, increases rate limit from 60 to 5000 req/hr) |
| `SYNC_ENABLED` | `false` | Enable rclone sync |
| `SYNC_REMOTE` | - | rclone remote name (required when sync enabled) |
| `SYNC_FOLDER` | `wet-mcp` | Remote folder name (optional) |
| `SYNC_INTERVAL` | `0` | Auto-sync interval in seconds, 0=manual (optional) |
| `LOG_LEVEL` | `INFO` | Logging level (optional) |

### Embedding & Reranking

Auto-detection logic:

- **Embedding**: `API_KEYS` set → cloud (Gemini > OpenAI > Mistral > Cohere). No API keys → local Qwen3-Embedding-0.6B (ONNX, CPU).
- **Reranking**: `RERANK_MODEL` set → cloud (e.g. `cohere/rerank-v3.5`). No RERANK_MODEL → local Qwen3-Reranker-0.6B (ONNX, CPU).
- All embeddings stored at **768 dims** (default). Switching providers never breaks the vector table.
- Override with `EMBEDDING_BACKEND=local` to force local even with API keys.

### LLM Configuration (Optional)

For media analysis, configure API keys:

```bash
API_KEYS=GOOGLE_API_KEY:AIza...
LLM_MODELS=gemini/gemini-3-flash-preview
```

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    MCP Client                           │
│            (Claude, Cursor, Windsurf)                   │
└─────────────────────┬───────────────────────────────────┘
                      │ MCP Protocol
                      v
┌─────────────────────────────────────────────────────────┐
│                   WET MCP Server                        │
│  ┌──────────┐  ┌──────────┐  ┌───────┐  ┌────────┐      │
│  │  search  │  │ extract  │  │ media │  │ config │      │
│  │ (search, │  │(extract, │  │(list, │  │(status,│      │
│  │ research,│  │ crawl,   │  │downld,│  │ set,   │      │
│  │ docs)    │  │ map)     │  │analyz)│  │ cache) │      │
│  └──┬───┬───┘  └────┬─────┘  └──┬────┘  └────────┘      │
│     │   │           │           │        + help tool     │
│     v   v           v           v                       │
│  ┌──────┐ ┌──────┐ ┌──────────┐ ┌──────────┐             │
│  │SearX │ │DocsDB│ │ Crawl4AI │ │ Reranker │             │
│  │NG    │ │FTS5+ │ │(Playwrgt)│ │(LiteLLM/ │             │
│  │      │ │sqlite│ │          │ │ Qwen3    │             │
│  │      │ │-vec  │ │          │ │ local)   │             │
│  └──────┘ └──────┘ └──────────┘ └──────────┘             │
│                                                         │
│  ┌──────────────────────────────────────────────────┐   │
│  │  WebCache (SQLite, TTL)  │  rclone sync (docs)   │   │
│  └──────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────┘
```

---

## Build from Source

```bash
git clone https://github.com/n24q02m/wet-mcp
cd wet-mcp

# Setup (requires mise: https://mise.jdx.dev/)
mise run setup

# Run
uv run wet-mcp
```

### Docker Build

```bash
docker build -t n24q02m/wet-mcp:latest .
```

**Requirements:** Python 3.13 (not 3.14+)

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md)

## License

MIT - See [LICENSE](LICENSE)
