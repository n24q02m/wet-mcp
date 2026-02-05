# WET - Web ExTract MCP Server

**Open-source MCP Server for web scraping & multimodal extraction.**

[![PyPI](https://img.shields.io/pypi/v/wet-mcp)](https://pypi.org/project/wet-mcp/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

## Features

- **Web Search** - Search via SearXNG (metasearch: Google, Bing, DuckDuckGo, Brave)
- **Content Extract** - Extract clean content (Markdown/Text)
- **Deep Crawl** - Crawl multiple pages from a root URL with depth control
- **Site Map** - Discover website URL structure
- **Media** - List and download images, videos, audio files
- **Anti-bot** - Stealth mode bypasses Cloudflare, Medium, LinkedIn, Twitter

---

## Quick Start

### Prerequisites

- **Docker** running (for SearXNG auto-management)
- **Python 3.13+** (or use `uvx`)

### Add to mcp.json

```json
{
  "mcpServers": {
    "wet": {
      "command": "uvx",
      "args": ["wet-mcp"]
    }
  }
}
```

**That's it!** On first run:
1. Automatically installs Playwright chromium
2. Automatically pulls SearXNG Docker image
3. Starts `wet-searxng` container
4. Runs the MCP server

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
| `WET_AUTO_DOCKER` | `true` | Auto-manage SearXNG container |
| `WET_SEARXNG_PORT` | `8080` | SearXNG container port |
| `SEARXNG_URL` | `http://localhost:8080` | External SearXNG URL |
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
│  │ (Docker) │  │(Playwright)│                           │
│  └──────────┘  └──────────┘                             │
└─────────────────────────────────────────────────────────┘
```

---

## Container Management

```bash
# View SearXNG logs
docker logs wet-searxng

# Stop SearXNG
docker stop wet-searxng

# Remove container (will be recreated on next run)
docker rm wet-searxng

# Reset auto-setup (forces re-install Playwright)
rm ~/.wet-mcp/.setup-complete
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

**Requirements:** Python 3.13+, Docker

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md)

## License

MIT - See [LICENSE](LICENSE)
