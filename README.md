# WET - Web ExTract MCP Server

**Open-source MCP Server for web scraping & multimodal extraction.**

[![PyPI](https://img.shields.io/pypi/v/wet-mcp)](https://pypi.org/project/wet-mcp/)
[![Docker](https://img.shields.io/docker/v/n24q02m/wet-mcp?label=docker)](https://hub.docker.com/r/n24q02m/wet-mcp)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

## Features

- **Web Search** - Search via embedded SearXNG (metasearch: Google, Bing, DuckDuckGo, Brave)
- **Content Extract** - Extract clean content (Markdown/Text)
- **Deep Crawl** - Crawl multiple pages from a root URL with depth control
- **Site Map** - Discover website URL structure
- **Media** - List and download images, videos, audio files
- **Anti-bot** - Stealth mode bypasses Cloudflare, Medium, LinkedIn, Twitter

---

## Quick Start

### Prerequisites

- **Python 3.13** (required — Python 3.14+ is **not** supported due to SearXNG incompatibility)

### Add to mcp.json

#### uvx (Recommended)

```json
{
  "mcpServers": {
    "wet": {
      "command": "uvx",
      "args": ["--python", "3.13", "wet-mcp@latest"],
      "env": {
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

```json
{
  "mcpServers": {
    "wet": {
      "command": "docker",
      "args": ["run", "-i", "--rm", "-e", "API_KEYS", "n24q02m/wet-mcp:latest"],
      "env": {
        "API_KEYS": "GOOGLE_API_KEY:AIza..."
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
| `web` | search, extract, crawl, map | Web operations |
| `media` | list, download, analyze | Media discovery & download |
| `help` | - | Full documentation |

### Usage Examples

```json
{"action": "search", "query": "python web scraping", "max_results": 10}
{"action": "extract", "urls": ["https://example.com"]}
{"action": "crawl", "urls": ["https://docs.python.org"], "depth": 2}
{"action": "map", "urls": ["https://example.com"]}
{"action": "list", "url": "https://github.com/python/cpython"}
{"action": "download", "media_urls": ["https://example.com/image.png"]}
```

---

## Configuration

| Variable | Default | Description |
|:---------|:--------|:------------|
| `WET_AUTO_SEARXNG` | `true` | Auto-start embedded SearXNG subprocess |
| `WET_SEARXNG_PORT` | `8080` | SearXNG port |
| `SEARXNG_URL` | `http://localhost:8080` | External SearXNG URL (when auto disabled) |
| `API_KEYS` | - | LLM API keys for media analysis |
| `LOG_LEVEL` | `INFO` | Logging level |

### LLM Configuration (Optional)

For media analysis (images, videos, audio), configure API keys:

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
                      ▼
┌─────────────────────────────────────────────────────────┐
│                   WET MCP Server                        │
│  ┌──────────┐  ┌──────────┐  ┌──────────────────────┐   │
│  │   web    │  │  media   │  │        help          │   │
│  │ (search, │  │ (list,   │  │  (full documentation)│   │
│  │ extract, │  │ download,│  └──────────────────────┘   │
│  │ crawl,   │  │ analyze) │                             │
│  │ map)     │  └────┬─────┘                             │
│  └────┬─────┘       │                                   │
│       │             │                                   │
│       ▼             ▼                                   │
│  ┌──────────┐  ┌──────────┐                             │
│  │ SearXNG  │  │ Crawl4AI │                             │
│  │(embedded)│  │(Playwright)│                           │
│  └──────────┘  └──────────┘                             │
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
