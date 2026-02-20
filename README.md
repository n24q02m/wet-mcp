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

### Option 1: uvx (Recommended)

```jsonc
{
  "mcpServers": {
    "wet": {
      "command": "uvx",
      "args": ["--python", "3.13", "wet-mcp@latest"],
      "env": {
        // -- optional: cloud embedding (Gemini > OpenAI > Cohere) + media analysis
        // -- without this, uses built-in local Qwen3-Embedding-0.6B + Qwen3-Reranker-0.6B (ONNX, CPU)
        // -- first run downloads ~570MB model, cached for subsequent runs
        "API_KEYS": "GOOGLE_API_KEY:AIza...",
        // -- optional: higher rate limits for docs discovery (60 -> 5000 req/hr)
        "GITHUB_TOKEN": "ghp_...",
        // -- optional: sync indexed docs across machines via rclone
        "SYNC_ENABLED": "true",                    // optional, default: false
        "SYNC_REMOTE": "gdrive",                   // required when SYNC_ENABLED=true
        "SYNC_INTERVAL": "300",                    // optional, auto-sync every 5min (0 = manual only)
        "RCLONE_CONFIG_GDRIVE_TYPE": "drive",      // required when SYNC_ENABLED=true
        "RCLONE_CONFIG_GDRIVE_TOKEN": "<base64>"   // required when SYNC_ENABLED=true, from: uvx --python 3.13 wet-mcp setup-sync drive
      }
    }
  }
}
```

### Option 2: Docker

```jsonc
{
  "mcpServers": {
    "wet": {
      "command": "docker",
      "args": [
        "run", "-i", "--rm",
        "--name", "mcp-wet",
        "-v", "wet-data:/data",                    // persists cached web pages, indexed docs, and downloads
        "-e", "API_KEYS",                          // optional: pass-through from env below
        "-e", "GITHUB_TOKEN",                      // optional: pass-through from env below
        "-e", "SYNC_ENABLED",                      // optional: pass-through from env below
        "-e", "SYNC_REMOTE",                       // required when SYNC_ENABLED=true: pass-through
        "-e", "SYNC_INTERVAL",                     // optional: pass-through from env below
        "-e", "RCLONE_CONFIG_GDRIVE_TYPE",         // required when SYNC_ENABLED=true: pass-through
        "-e", "RCLONE_CONFIG_GDRIVE_TOKEN",        // required when SYNC_ENABLED=true: pass-through
        "n24q02m/wet-mcp:latest"
      ],
      "env": {
        // -- optional: cloud embedding (Gemini > OpenAI > Cohere) + media analysis
        // -- without this, uses built-in local Qwen3-Embedding-0.6B + Qwen3-Reranker-0.6B (ONNX, CPU)
        "API_KEYS": "GOOGLE_API_KEY:AIza...",
        // -- optional: higher rate limits for docs discovery (60 -> 5000 req/hr)
        "GITHUB_TOKEN": "ghp_...",
        // -- optional: sync indexed docs across machines via rclone
        "SYNC_ENABLED": "true",                    // optional, default: false
        "SYNC_REMOTE": "gdrive",                   // required when SYNC_ENABLED=true
        "SYNC_INTERVAL": "300",                    // optional, auto-sync every 5min (0 = manual only)
        "RCLONE_CONFIG_GDRIVE_TYPE": "drive",      // required when SYNC_ENABLED=true
        "RCLONE_CONFIG_GDRIVE_TOKEN": "<base64>"   // required when SYNC_ENABLED=true, from: uvx --python 3.13 wet-mcp setup-sync drive
      }
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
| `EMBEDDING_BACKEND` | (auto-detect) | `litellm` (cloud API) or `local` (Qwen3). Auto: API_KEYS -> litellm, else local (always available) |
| `EMBEDDING_MODEL` | (auto-detect) | LiteLLM embedding model (optional) |
| `EMBEDDING_DIMS` | `0` (auto=768) | Embedding dimensions (optional) |
| `RERANK_ENABLED` | `true` | Enable reranking after search |
| `RERANK_BACKEND` | (auto-detect) | `litellm` or `local`. Auto: Cohere key in API_KEYS -> litellm, else local |
| `RERANK_MODEL` | (auto-detect) | LiteLLM rerank model (auto: `cohere/rerank-multilingual-v3.0` if Cohere key in API_KEYS) |
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

Both embedding and reranking are **always available** — local models are built-in and require no configuration.

- **Embedding**: Default local Qwen3-Embedding-0.6B. Set `API_KEYS` to upgrade to cloud (Gemini > OpenAI > Cohere), with automatic local fallback if cloud fails.
- **Reranking**: Default local Qwen3-Reranker-0.6B. If `COHERE_API_KEY` is present in `API_KEYS`, auto-upgrades to cloud `cohere/rerank-multilingual-v3.0`.
- **GPU auto-detection**: If GPU is available (CUDA/DirectML) and `llama-cpp-python` is installed, automatically uses GGUF models (~480MB) instead of ONNX (~570MB) for better performance.
- All embeddings stored at **768 dims** (default). Switching providers never breaks the vector table.
- Override with `EMBEDDING_BACKEND=local` to force local even with API keys.

`API_KEYS` supports multiple providers in a single string:
```
API_KEYS=GOOGLE_API_KEY:AIza...,OPENAI_API_KEY:sk-...,COHERE_API_KEY:co-...
```

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
