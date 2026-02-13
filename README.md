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

### Add to mcp.json

#### uvx (Recommended)

```jsonc
{
  "mcpServers": {
    "wet": {
      "command": "uvx",
      "args": ["--python", "3.13", "wet-mcp@latest"],
      "env": {
        // Optional: API keys for embedding and media analysis
        "API_KEYS": "GOOGLE_API_KEY:AIza..."
      }
    }
  }
}
```

> **Warning:** You **must** specify `--python 3.13` when using `uvx`. Without it, `uvx` may pick Python 3.14+ which causes SearXNG search to fail silently (`RuntimeError: can't register atexit after shutdown` in DNS resolution).

**That's it!** On first run:
1. Automatically installs SearXNG from GitHub
2. Automatically installs Playwright chromium + system dependencies
3. Starts embedded SearXNG subprocess
4. Runs the MCP server

#### Docker

```jsonc
{
  "mcpServers": {
    "wet": {
      "command": "docker",
      "args": [
        "run", "-i", "--rm",
        "-v", "wet-data:/data",
        "-e", "API_KEYS",
        "n24q02m/wet-mcp:latest"
      ],
      "env": {
        "API_KEYS": "GOOGLE_API_KEY:AIza..."
      }
    }
  }
}
```

> The `-v wet-data:/data` volume mount persists cached web pages, indexed library docs, and downloaded media across container restarts.

#### With docs sync (Google Drive)

**Step 1**: Get a drive token (one-time, requires browser):

```bash
uvx --python 3.13 wet-mcp setup-sync drive
```

This downloads rclone, opens a browser for Google Drive auth, and outputs a **base64-encoded token** for `RCLONE_CONFIG_GDRIVE_TOKEN`.

**Step 2**: Copy the token and add it to your MCP config:

```jsonc
{
  "mcpServers": {
    "wet": {
      "command": "uvx",
      "args": ["--python", "3.13", "wet-mcp@latest"],
      "env": {
        "API_KEYS": "GOOGLE_API_KEY:AIza...", // optional: enables media analysis & docs embedding
        "SYNC_ENABLED": "true",               // required for sync
        "SYNC_REMOTE": "gdrive",               // required: rclone remote name
        "SYNC_INTERVAL": "300",                // optional: auto-sync seconds (default: 0 = manual)
        // "SYNC_FOLDER": "wet-mcp",            // optional: remote folder (default: wet-mcp)
        "RCLONE_CONFIG_GDRIVE_TYPE": "drive",  // required: rclone backend type
        "RCLONE_CONFIG_GDRIVE_TOKEN": "<paste base64 token>" // required: from setup-sync
      }
    }
  }
}
```

Both raw JSON and base64-encoded tokens are supported. Base64 is recommended — it avoids nested JSON escaping issues.

Remote is configured via env vars — works in any environment (local, Docker, CI).

#### With sync in Docker

```jsonc
{
  "mcpServers": {
    "wet": {
      "command": "docker",
      "args": [
        "run", "-i", "--rm",
        "-v", "wet-data:/data",
        "-e", "API_KEYS",
        "-e", "SYNC_ENABLED",
        "-e", "SYNC_REMOTE",
        "-e", "SYNC_INTERVAL",              // optional: remove if manual sync only
        "-e", "RCLONE_CONFIG_GDRIVE_TYPE",
        "-e", "RCLONE_CONFIG_GDRIVE_TOKEN",
        "n24q02m/wet-mcp:latest"
      ],
      "env": {
        "API_KEYS": "GOOGLE_API_KEY:AIza...", // optional: enables media analysis & docs embedding
        "SYNC_ENABLED": "true",               // required for sync
        "SYNC_REMOTE": "gdrive",               // required: rclone remote name
        "SYNC_INTERVAL": "300",                // optional: auto-sync seconds (default: 0 = manual)
        // "SYNC_FOLDER": "wet-mcp",            // optional: remote folder (default: wet-mcp)
        "RCLONE_CONFIG_GDRIVE_TYPE": "drive",  // required: rclone backend type
        "RCLONE_CONFIG_GDRIVE_TOKEN": "<paste base64 token>" // required: from setup-sync
      }
    }
  }
}
```

### Without uvx

```bash
pip install wet-mcp
wet-mcp
```

---

## Tools

| Tool | Actions | Description |
|:-----|:--------|:------------|
| `search` | search, research, docs | Web search, academic research, library documentation |
| `extract` | extract, crawl, map | Content extraction, deep crawling, site mapping |
| `media` | list, download, analyze | Media discovery & download |
| `help` | - | Full documentation for any tool |

### Usage Examples

```json
// search tool
{"action": "search", "query": "python web scraping", "max_results": 10}
{"action": "research", "query": "transformer attention mechanism"}
{"action": "docs", "query": "how to create routes", "library": "fastapi"}

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
| `WET_SEARXNG_PORT` | `8080` | SearXNG port (optional) |
| `SEARXNG_URL` | `http://localhost:8080` | External SearXNG URL (optional, when auto disabled) |
| `SEARXNG_TIMEOUT` | `30` | SearXNG request timeout in seconds (optional) |
| `API_KEYS` | - | LLM API keys (optional, format: `ENV_VAR:key,...`) |
| `LLM_MODELS` | `gemini/gemini-3-flash-preview` | LiteLLM model for media analysis (optional) |
| `EMBEDDING_MODEL` | (auto-detect) | LiteLLM embedding model for docs vector search (optional) |
| `EMBEDDING_DIMS` | `0` (auto=768) | Embedding dimensions (optional) |
| `CACHE_DIR` | `~/.wet-mcp` | Data directory for cache DB, docs DB, downloads (optional) |
| `DOCS_DB_PATH` | `~/.wet-mcp/docs.db` | Docs database location (optional) |
| `DOWNLOAD_DIR` | `~/.wet-mcp/downloads` | Media download directory (optional) |
| `TOOL_TIMEOUT` | `120` | Tool execution timeout in seconds, 0=no timeout (optional) |
| `WET_CACHE` | `true` | Enable/disable web cache (optional) |
| `SYNC_ENABLED` | `false` | Enable rclone sync |
| `SYNC_REMOTE` | - | rclone remote name (required when sync enabled) |
| `SYNC_FOLDER` | `wet-mcp` | Remote folder name (optional) |
| `SYNC_INTERVAL` | `0` | Auto-sync interval in seconds, 0=manual (optional) |
| `LOG_LEVEL` | `INFO` | Logging level (optional) |

### LLM Configuration (Optional)

For media analysis and docs embedding, configure API keys:

```bash
API_KEYS=GOOGLE_API_KEY:AIza...
LLM_MODELS=gemini/gemini-3-flash-preview
```

The server auto-detects embedding models from configured API keys (Gemini > OpenAI > Mistral > Cohere).

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
│  ┌──────────┐  ┌──────────┐  ┌───────┐  ┌──────────┐   │
│  │  search  │  │ extract  │  │ media │  │   help   │   │
│  │ (search, │  │(extract, │  │(list, │  │          │   │
│  │ research,│  │ crawl,   │  │downld,│  │          │   │
│  │ docs)    │  │ map)     │  │analyz)│  │          │   │
│  └──┬───┬───┘  └────┬─────┘  └──┬────┘  └──────────┘   │
│     │   │           │           │                       │
│     v   v           v           v                       │
│  ┌──────┐ ┌──────┐ ┌──────────┐                         │
│  │SearX │ │DocsDB│ │ Crawl4AI │                         │
│  │NG    │ │FTS5+ │ │(Playwrgt)│                         │
│  │      │ │sqlite│ │          │                         │
│  │      │ │-vec  │ │          │                         │
│  └──────┘ └──────┘ └──────────┘                         │
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
