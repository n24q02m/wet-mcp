# WET - Web ExTract MCP Server

> **Open-source MCP Server thay thế Tavily cho web scraping & multimodal extraction**

Zero-install experience: chỉ cần `uvx wet-mcp` - tự động quản lý SearXNG container.

## Features

- **Web Search**: Tìm kiếm qua SearXNG (metasearch: Google, Bing, DuckDuckGo, etc.)
- **Content Extract**: Trích xuất nội dung sạch (Markdown/Text/HTML)
- **Deep Crawl**: Đi qua nhiều trang con từ URL gốc
- **Site Map**: Khám phá cấu trúc URL của website
- **Multimodal**: List và download images, videos, audio, files
- **Anti-bot**: Stealth mode, undetected browser bypass

## Tech Stack

| Component | Technology |
|:----------|:-----------|
| Language | Python 3.12 |
| MCP Framework | FastMCP |
| Web Search | SearXNG (auto-managed) |
| Web Crawling | Crawl4AI |
| Docker Management | python-on-whales |

## Quick Start

### Prerequisites

- Docker daemon running
- Python 3.12+ (hoặc dùng uvx)

### MCP Client Configuration

#### Claude Desktop / Cursor / Windsurf

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
1. Tự động pull SearXNG image
2. Start `wet-searxng` container
3. Chạy MCP server

### Without uvx

```bash
pip install wet-mcp
wet-mcp
```

## Tools

| Tool | Actions | Description |
|:-----|:--------|:------------|
| `web` | search, extract, crawl, map | Web operations |
| `media` | list, download | Multimodal discovery & download |
| `help` | - | Full documentation |

## How It Works

```python
# When you run: uvx wet-mcp
# The package automatically:

from python_on_whales import docker

def ensure_searxng():
    """Start SearXNG container if not running."""
    if not docker.container.exists("wet-searxng"):
        docker.run(
            "searxng/searxng:latest",
            name="wet-searxng",
            detach=True,
            publish=[(8080, 8080)],
        )
```

## Container Management

```bash
# View SearXNG logs
docker logs wet-searxng

# Stop SearXNG
docker stop wet-searxng

# Remove container
docker rm wet-searxng
```

## Documentation

- [Developer Handbook](docs/HANDBOOK.md)

## License

MIT License
