# WET MCP SERVER - DEVELOPER HANDBOOK

**Phiên bản:** 0.1.0
**Ngày cập nhật:** 03/02/2026
**Dành cho:** Solo Developer / Team

---

## MỤC LỤC

1. [TỔNG QUAN DỰ ÁN](#1-tổng-quan-dự-án)
2. [VISION VÀ SCOPE](#2-vision-và-scope)
3. [KIẾN TRÚC HỆ THỐNG](#3-kiến-trúc-hệ-thống)
4. [CÔNG NGHỆ STACK](#4-công-nghệ-stack)
5. [TOOL DESIGN](#5-tool-design)
6. [ANTI-BOT MECHANISMS](#6-anti-bot-mechanisms)
7. [QUY TRÌNH PHÁT TRIỂN](#7-quy-trình-phát-triển)
8. [DEPLOYMENT](#8-deployment)
9. [TESTING](#9-testing)

---

## 1. TỔNG QUAN DỰ ÁN

### 1.1. Giới Thiệu

**WET (Web ExTract)** là một MCP Server open-source thay thế Tavily MCP Server, cung cấp khả năng:
- Web search qua SearXNG
- Content extraction qua Crawl4AI
- Multimodal data discovery (images, videos, audio, files)

**Điểm Nổi Bật:**
- **100% Open-source & Free**: Không cần API key của third-party
- **Self-hosted**: Docker Compose bundle SearXNG sẵn
- **LLM-free extraction**: CSS/XPath/Regex strategies
- **Anti-bot bypass**: Stealth mode, undetected browser

### 1.2. So Sánh Với Tavily

| Feature | Tavily | WET |
|:--------|:-------|:----|
| Pricing | $0.004/search | Free |
| Self-hosted | ❌ | ✅ |
| Search | Tavily API | SearXNG (metasearch) |
| Extract | Tavily API | Crawl4AI |
| Crawl | ✅ | ✅ |
| Map | ✅ | ✅ |
| Multimodal | ❌ | ✅ |
| Anti-bot | Basic | Advanced (Stealth) |
| Docker | N/A | Multi-container |

### 1.3. Nguồn Cảm Hứng

Dựa trên patterns từ:
- **better-notion-mcp**: Composite tools, action-based API
- **better-mem0-mcp**: Tiered descriptions, help tool

---

## 2. VISION VÀ SCOPE

### 2.1. Core Philosophy

- **Zero API Keys**: Không yêu cầu đăng ký bất kỳ third-party service nào
- **Docker-first**: Single command để chạy toàn bộ stack
- **MCP Client decides**: WET chỉ cung cấp data, client quyết định xử lý

### 2.2. Key Features

#### A. Web Tool
- **search**: Tìm kiếm web qua SearXNG (categories: web, images, videos, files)
- **extract**: Lấy nội dung sạch từ URL (Markdown/Text/HTML)
- **crawl**: Đi qua nhiều trang con từ root URL
- **map**: Khám phá cấu trúc sitemap

#### B. Media Tool
- **list**: Scan page, trả về URLs + metadata
- **download**: Tải files về local

### 2.3. Non-Features (Out of Scope v1.0)

- ❌ LLM-based extraction (optional, user tự config)
- ❌ Media analysis (OCR, transcription) - MCP client tự quyết định
- ❌ Browser automation scripting
- ❌ JavaScript rendering configuration

---

## 3. KIẾN TRÚC HỆ THỐNG

### 3.1. Overview

```text
┌─────────────────────────────────────────────────────────────┐
│              MCP Client (Claude/Cursor/etc.)               │
│                    Gọi tools qua stdio                      │
└─────────────────────────────────────────────────────────────┘
                              │
                              v
┌─────────────────────────────────────────────────────────────┐
│                    WET MCP Server                           │
│   ┌─────────────┐  ┌─────────────┐  ┌─────────────┐        │
│   │  web tool   │  │ media tool  │  │  help tool  │        │
│   └─────────────┘  └─────────────┘  └─────────────┘        │
│          │                │                                 │
│          v                v                                 │
│   ┌─────────────────────────────────────────────┐          │
│   │           Core Services                      │          │
│   │   SearXNG Client │ Crawl4AI Wrapper         │          │
│   └─────────────────────────────────────────────┘          │
└─────────────────────────────────────────────────────────────┘
                              │
                              v
┌─────────────────────────────────────────────────────────────┐
│                    SearXNG Container                        │
│            Metasearch (Google, Bing, DDG, etc.)            │
└─────────────────────────────────────────────────────────────┘
```

### 3.2. Project Structure

```text
wet-mcp/
├── .github/workflows/
│   ├── ci.yml              # Lint, test
│   └── release.yml         # Publish to PyPI
├── src/wet_mcp/
│   ├── __init__.py
│   ├── __main__.py         # Entry point + Docker management
│   ├── server.py           # MCP Server definition
│   ├── config.py           # Settings từ env vars
│   ├── docker_manager.py   # python-on-whales wrapper
│   ├── docs/               # Tier 2 documentation
│   ├── sources/
│   │   ├── searxng.py      # SearXNG HTTP client
│   │   └── crawler.py      # Crawl4AI wrapper
│   └── utils/
├── tests/
├── pyproject.toml
├── mise.toml
└── README.md
```

---

## 4. CÔNG NGHỆ STACK

### 4.1. Core Stack

| Layer | Technology | Notes |
|:------|:-----------|:------|
| **Language** | Python 3.12 | AI/ML ecosystem |
| **MCP Framework** | FastMCP | Simple, async-first |
| **Web Search** | SearXNG | Metasearch engine (auto-managed) |
| **Web Crawling** | Crawl4AI | LLM-friendly, anti-bot |
| **Docker Management** | python-on-whales | Auto start/stop containers |
| **HTTP Client** | httpx | Async support |

### 4.2. Dependencies

```toml
[project]
dependencies = [
    "mcp",
    "python-on-whales>=0.73.0",
    "crawl4ai>=0.8.0",
    "httpx>=0.27.0",
    "pydantic>=2.0",
    "pydantic-settings>=2.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.24",
    "ruff>=0.8",
]
```

### 4.3. SearXNG Configuration

```yaml
# docker/searxng/settings.yml
use_default_settings: true

server:
  secret_key: "wet-mcp-internal"
  limiter: false  # Internal use only

search:
  formats:
    - html
    - json  # Required for API
  safe_search: 0
  autocomplete: false

engines:
  # Enable specific engines
  - name: google
    disabled: false
  - name: duckduckgo
    disabled: false
  - name: bing
    disabled: false
```

---

## 5. TOOL DESIGN

### 5.1. Tiered Descriptions

| Tier | Location | Purpose |
|:-----|:---------|:--------|
| **Tier 1** | Tool docstring | Compressed, fits token budget |
| **Tier 2** | `docs/*.md` | Full documentation via `help` tool |
| **Tier 3** | MCP Resources | Future: dynamic examples |

### 5.2. Tool: `web`

```python
@mcp.tool()
async def web(
    action: str,           # "search" | "extract" | "crawl" | "map"
    query: str = None,     # For search
    urls: list[str] = None,# For extract/crawl/map
    # Search options
    categories: str = "general",  # general, images, videos, files
    max_results: int = 10,
    # Crawl options
    depth: int = 2,
    max_pages: int = 20,
    # Output options
    format: str = "markdown",  # "markdown" | "text" | "html"
    stealth: bool = True,      # Enable anti-bot
) -> str:
    """
    Web operations: search, extract, crawl, map.
    - search: Web search via SearXNG (requires query)
    - extract: Get clean content from URLs
    - crawl: Deep crawl from root URL
    - map: Discover site structure
    Use `help` tool for full documentation.
    """
```

**Actions:**

| Action | Required Params | Returns |
|:-------|:----------------|:--------|
| `search` | `query` | List of results with URL, title, snippet |
| `extract` | `urls` | Markdown content from each URL |
| `crawl` | `urls` | Content from root + child pages |
| `map` | `urls` | List of discovered URLs |

### 5.3. Tool: `media`

```python
@mcp.tool()
async def media(
    action: str,           # "list" | "download"
    url: str = None,       # Page URL to scan
    media_type: str = "all",  # "images" | "videos" | "audio" | "files" | "all"
    # Download options
    media_urls: list[str] = None,  # Specific URLs to download
    output_dir: str = None,        # Default: ~/.wet-mcp/downloads/
    max_items: int = 10,
) -> str:
    """
    Media discovery and download.
    - list: Scan page, return URLs + metadata
    - download: Download specific files to local
    MCP client decides whether to analyze media.
    Use `help` tool for full documentation.
    """
```

**Media Metadata Format:**

```json
{
  "images": [
    {"src": "https://...", "alt": "description", "score": 5, "type": "png"}
  ],
  "videos": [
    {"src": "https://...", "title": "Video title", "score": 3}
  ],
  "audio": [
    {"src": "https://...", "title": "Audio title"}
  ]
}
```

### 5.4. Tool: `help`

```python
@mcp.tool()
async def help(tool_name: str = "web") -> str:
    """
    Get full documentation for a tool.
    Use when compressed descriptions are insufficient.
    """
    return _load_doc(tool_name)
```

---

## 6. ANTI-BOT MECHANISMS

### 6.1. Levels

| Level | Feature | When to Use |
|:------|:--------|:------------|
| **Level 1** | Regular Browser | Basic sites |
| **Level 2** | Stealth Mode (default) | Most sites |
| **Level 3** | Undetected Browser | Cloudflare, Datadome |

### 6.2. Stealth Mode Features

```python
BrowserConfig(
    enable_stealth=True,   # Default in WET
    headless=True,         # Docker-friendly
)
```

**What it does:**
- Removes `navigator.webdriver` flag
- Emulates realistic plugins & languages
- Patches Chrome DevTools Protocol (CDP) detection
- Randomizes fingerprints

### 6.3. Undetected Browser

```python
BrowserConfig(
    browser_mode="undetected",
    enable_stealth=True,
)
```

**When to use:**
- Sites with advanced bot detection (Cloudflare, Datadome)
- Rate-limited sites
- Sites blocking headless browsers

---

## 7. QUY TRÌNH PHÁT TRIỂN

### 7.1. Setup Môi Trường

```bash
# Prerequisites
mise install  # Installs Python, pnpm, uv

# Install dependencies
uv sync

# Run tests
uv run pytest

# Run server locally (cần SearXNG external)
SEARXNG_URL=https://searx.be uv run python -m wet_mcp
```

### 7.2. Docker Development

```bash
# Build và chạy
docker compose up --build

# Chỉ SearXNG
docker compose up searxng

# Test với MCP client
docker exec -i wet-mcp python -m wet_mcp
```

### 7.3. Code Quality

| Tool | Purpose |
|:-----|:--------|
| `ruff` | Linting + formatting |
| `ty` | Type checking |
| `pytest` | Testing |
| `pre-commit` | Git hooks |

```bash
# Format + lint
uv run ruff check --fix .
uv run ruff format .

# Type check
uv run ty check src/

# All checks
mise run check
```

---

## 8. DEPLOYMENT

### 8.1. Docker Compose (Recommended)

```yaml
# docker/docker-compose.yml
services:
  wet-mcp:
    build:
      context: ..
      dockerfile: docker/Dockerfile
    depends_on:
      - searxng
    environment:
      - SEARXNG_URL=http://searxng:8080
    volumes:
      - wet-downloads:/root/.wet-mcp/downloads

  searxng:
    image: searxng/searxng:latest
    volumes:
      - ./searxng/settings.yml:/etc/searxng/settings.yml:ro
    healthcheck:
      test: ["CMD", "wget", "-q", "--spider", "http://localhost:8080/healthz"]
      interval: 30s
      timeout: 10s
      retries: 3

volumes:
  wet-downloads:
```

### 8.2. Dockerfile

```dockerfile
FROM python:3.12-slim

# Install Playwright dependencies
RUN apt-get update && apt-get install -y \
    wget gnupg \
    && rm -rf /var/lib/apt/lists/*

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

COPY src/ src/

# Install Playwright browsers
RUN uv run playwright install chromium --with-deps

CMD ["uv", "run", "python", "-m", "wet_mcp"]
```

### 8.3. Environment Variables

| Variable | Required | Default | Description |
|:---------|:---------|:--------|:------------|
| `SEARXNG_URL` | ❌ | http://localhost:8080 | SearXNG instance URL (auto-managed) |
| `SEARXNG_TIMEOUT` | ❌ | 30 | Request timeout (seconds) |
| `CRAWLER_HEADLESS` | ❌ | true | Run browser headless |
| `CRAWLER_TIMEOUT` | ❌ | 60 | Page load timeout |
| `DOWNLOAD_DIR` | ❌ | ~/.wet-mcp/downloads | Media download directory |
| `WET_AUTO_DOCKER` | ❌ | true | Auto-manage SearXNG container |

### 8.4. Embedded Docker Management

Package tự động quản lý SearXNG container:

```python
# docker_manager.py
from python_on_whales import docker, DockerException

CONTAINER_NAME = "wet-searxng"
SEARXNG_IMAGE = "searxng/searxng:latest"

def ensure_searxng() -> str:
    """Start SearXNG container if not running. Returns URL."""
    try:
        if not docker.container.exists(CONTAINER_NAME):
            docker.run(
                SEARXNG_IMAGE,
                name=CONTAINER_NAME,
                detach=True,
                publish=[(8080, 8080)],
                envs={"SEARXNG_SECRET": "wet-internal"},
            )
        elif not docker.container.inspect(CONTAINER_NAME).state.running:
            docker.container.start(CONTAINER_NAME)
        return "http://localhost:8080"
    except DockerException as e:
        raise RuntimeError(f"Docker not available: {e}")
```

### 8.5. MCP Client Configuration

#### Claude Desktop / Cursor / Windsurf (Recommended)

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

#### With External SearXNG (disable auto-docker)

```json
{
  "mcpServers": {
    "wet": {
      "command": "uvx",
      "args": ["wet-mcp"],
      "env": {
        "SEARXNG_URL": "https://searx.be",
        "WET_AUTO_DOCKER": "false"
      }
    }
  }
}
```

### 8.6. Container Management

```bash
# View SearXNG logs
docker logs wet-searxng

# Stop container (when not using wet-mcp)
docker stop wet-searxng

# Remove container
docker rm wet-searxng
```

---

## 9. TESTING

### 9.1. Test Structure

```text
tests/
├── conftest.py          # Fixtures
├── test_search.py       # SearXNG integration
├── test_extract.py      # Crawl4AI extraction
├── test_crawl.py        # Multi-page crawling
├── test_map.py          # Sitemap discovery
├── test_media.py        # Multimodal extraction
└── test_integration.py  # E2E tests
```

### 9.2. Running Tests

```bash
# All tests
uv run pytest

# With coverage
uv run pytest --cov=wet_mcp

# Only unit tests (mock SearXNG)
uv run pytest -m "not integration"

# Integration tests (requires Docker)
uv run pytest -m integration
```

### 9.3. Mock Fixtures

```python
# tests/conftest.py
import pytest
from unittest.mock import AsyncMock

@pytest.fixture
def mock_searxng():
    """Mock SearXNG API responses."""
    return AsyncMock(return_value={
        "results": [
            {"url": "https://example.com", "title": "Example", "content": "..."}
        ]
    })

@pytest.fixture
def mock_crawler():
    """Mock Crawl4AI responses."""
    return AsyncMock(return_value={
        "markdown": "# Example\n\nContent here...",
        "media": {"images": [], "videos": [], "audio": []}
    })
```

---

## PHỤ LỤC

### A. API Response Formats

#### Search Response

```json
{
  "results": [
    {
      "url": "https://example.com/article",
      "title": "Article Title",
      "snippet": "Brief description...",
      "source": "google"
    }
  ],
  "total": 10,
  "query": "original query"
}
```

#### Extract Response

```json
{
  "url": "https://example.com",
  "title": "Page Title",
  "content": "# Heading\n\nMarkdown content...",
  "links": {
    "internal": ["https://example.com/page1"],
    "external": ["https://other.com"]
  }
}
```

### B. Error Handling

| Error Code | Description | Recovery |
|:-----------|:------------|:---------|
| `SEARXNG_UNAVAILABLE` | SearXNG not responding | Check Docker, retry |
| `CRAWLER_TIMEOUT` | Page load timeout | Increase timeout, try later |
| `ANTI_BOT_DETECTED` | Bot detection triggered | Enable undetected mode |
| `DOWNLOAD_FAILED` | Media download failed | Check URL, retry |

### C. References

- [Crawl4AI Documentation](https://docs.crawl4ai.com/)
- [SearXNG Documentation](https://docs.searxng.org/)
- [Model Context Protocol](https://modelcontextprotocol.io/)
- [FastMCP](https://github.com/jlowin/fastmcp)
- [better-notion-mcp](https://github.com/n24q02m/better-notion-mcp)
- [better-mem0-mcp](https://github.com/n24q02m/better-mem0-mcp)
