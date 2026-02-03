# WET - Web ExTract MCP Server

[![PyPI version](https://badge.fury.io/py/wet-mcp.svg)](https://badge.fury.io/py/wet-mcp)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

> **Open-source MCP Server thay thế Tavily cho web scraping & multimodal extraction**

Zero-install experience: chỉ cần `uvx wet-mcp` - tự động setup và quản lý SearXNG container.

## Features

| Feature | Description |
|:--------|:------------|
| **Web Search** | Tìm kiếm qua SearXNG (metasearch: Google, Bing, DuckDuckGo, Brave) |
| **Content Extract** | Trích xuất nội dung sạch (Markdown/Text/HTML) |
| **Deep Crawl** | Đi qua nhiều trang con từ URL gốc với depth control |
| **Site Map** | Khám phá cấu trúc URL của website |
| **Media** | List và download images, videos, audio files |
| **Anti-bot** | Stealth mode bypass Cloudflare, Medium, LinkedIn, Twitter |

## Quick Start

### Prerequisites

- Docker daemon running (for SearXNG)
- Python 3.13+ (hoặc dùng uvx)

### MCP Client Configuration

**Claude Desktop / Cursor / Windsurf / Antigravity:**

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

**Đó là tất cả!** Khi MCP client gọi wet-mcp lần đầu:
1. Tự động install Playwright chromium
2. Tự động pull SearXNG Docker image
3. Start `wet-searxng` container
4. Chạy MCP server

### Without uvx

```bash
pip install wet-mcp
wet-mcp
```

## Tools

| Tool | Actions | Description |
|:-----|:--------|:------------|
| `web` | search, extract, crawl, map | Web operations |
| `media` | list, download | Media discovery & download |
| `help` | - | Full documentation |

### Examples

```python
# Search
{"action": "search", "query": "python web scraping", "max_results": 10}

# Extract content
{"action": "extract", "urls": ["https://example.com"]}

# Crawl with depth
{"action": "crawl", "urls": ["https://docs.python.org"], "depth": 2}

# Map site structure
{"action": "map", "urls": ["https://example.com"]}

# List media
{"action": "list", "url": "https://github.com/python/cpython"}

# Download media
{"action": "download", "media_urls": ["https://example.com/image.png"]}
```

## Tech Stack

| Component | Technology |
|:----------|:-----------|
| Language | Python 3.13 |
| MCP Framework | FastMCP |
| Web Search | SearXNG (auto-managed Docker) |
| Web Crawling | Crawl4AI |
| Docker Management | python-on-whales |

## How It Works

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
│  │ extract, │  │ download)│  └──────────────────────┘   │
│  │ crawl,   │  └────┬─────┘                             │
│  │ map)     │       │                                   │
│  └────┬─────┘       │                                   │
│       │             │                                   │
│       ▼             ▼                                   │
│  ┌──────────┐  ┌──────────┐                             │
│  │ SearXNG  │  │ Crawl4AI │                             │
│  │ (Docker) │  │(Playwright)│                           │
│  └──────────┘  └──────────┘                             │
└─────────────────────────────────────────────────────────┘
```

## Configuration

Environment variables:

| Variable | Default | Description |
|:---------|:--------|:------------|
| `WET_AUTO_DOCKER` | `true` | Auto-manage SearXNG container |
| `WET_SEARXNG_PORT` | `8080` | SearXNG container port |
| `SEARXNG_URL` | `http://localhost:8080` | External SearXNG URL |
| `LOG_LEVEL` | `INFO` | Logging level |

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

## License

MIT License
