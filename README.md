# WET - Web Extended Toolkit MCP Server

mcp-name: io.github.n24q02m/wet-mcp

**Open-source MCP Server for web search, content extraction, library docs & multimodal analysis.**

[![CI](https://github.com/n24q02m/wet-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/n24q02m/wet-mcp/actions/workflows/ci.yml)
[![codecov](https://codecov.io/gh/n24q02m/wet-mcp/graph/badge.svg?token=JK19TRLPEX)](https://codecov.io/gh/n24q02m/wet-mcp)
[![PyPI](https://img.shields.io/pypi/v/wet-mcp?logo=pypi&logoColor=white)](https://pypi.org/project/wet-mcp/)
[![Docker](https://img.shields.io/docker/v/n24q02m/wet-mcp?label=docker&logo=docker&logoColor=white&sort=semver)](https://hub.docker.com/r/n24q02m/wet-mcp)
[![License: MIT](https://img.shields.io/github/license/n24q02m/wet-mcp)](LICENSE)

[![Python](https://img.shields.io/badge/Python-3776AB?logo=python&logoColor=white)](#)
[![SearXNG](https://img.shields.io/badge/SearXNG-3050FF?logo=searxng&logoColor=white)](#)
[![MCP](https://img.shields.io/badge/MCP-000000?logo=anthropic&logoColor=white)](#)
[![semantic-release](https://img.shields.io/badge/semantic--release-e10079?logo=semantic-release&logoColor=white)](https://github.com/python-semantic-release/python-semantic-release)
[![Renovate](https://img.shields.io/badge/renovate-enabled-1A1F6C?logo=renovatebot&logoColor=white)](https://developer.mend.io/)

<a href="https://glama.ai/mcp/servers/n24q02m/wet-mcp">
  <img width="380" height="200" src="https://glama.ai/mcp/servers/n24q02m/wet-mcp/badge" alt="WET MCP server" />
</a>

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

The recommended way to run this server is via `uvx`:

```bash
uvx --python 3.13 wet-mcp@latest
```

> Alternatively, you can use `pipx run --python python3.13 wet-mcp`.

### Option 1: uvx (Recommended)

```jsonc
{
  "mcpServers": {
    "wet": {
      "command": "uvx",
      "args": ["--python", "3.13", "wet-mcp@latest"],
      "env": {
        // -- optional: LiteLLM Proxy (production, selfhosted gateway)
        // "LITELLM_PROXY_URL": "http://10.0.0.20:4000",
        // "LITELLM_PROXY_KEY": "sk-your-virtual-key",
        // -- optional: cloud embedding (Gemini > OpenAI > Cohere) + media analysis
        // -- without this, uses built-in local Qwen3-Embedding-0.6B + Qwen3-Reranker-0.6B (ONNX, CPU)
        // -- first run downloads ~570MB model, cached for subsequent runs
        "API_KEYS": "GOOGLE_API_KEY:AIza...",
        // -- optional: custom endpoints (e.g. modalcom-ai-workers on Modal.com)
        // "EMBEDDING_API_BASE": "https://your-worker.modal.run",
        // "EMBEDDING_API_KEY": "your-key",
        // "RERANK_API_BASE": "https://your-worker.modal.run",
        // "RERANK_API_KEY": "your-key",
        // -- optional: higher rate limits for docs discovery (60 -> 5000 req/hr)
        "GITHUB_TOKEN": "ghp_...",
        // -- optional: sync indexed docs across machines via rclone
        // -- on first sync, a browser opens for OAuth (auto, no manual setup)
        "SYNC_ENABLED": "true",                    // optional, default: false
        "SYNC_INTERVAL": "300"                     // optional, auto-sync every 5min (0 = manual only)
        // "SYNC_REMOTE": "gdrive",                 // optional, default: gdrive
        // "SYNC_PROVIDER": "drive",                // optional, default: drive (Google Drive)
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
        "-e", "LITELLM_PROXY_URL",                 // optional: pass-through from env below
        "-e", "LITELLM_PROXY_KEY",                 // optional: pass-through from env below
        "-e", "API_KEYS",                          // optional: pass-through from env below
        "-e", "EMBEDDING_API_BASE",                // optional: pass-through from env below
        "-e", "EMBEDDING_API_KEY",                 // optional: pass-through from env below
        "-e", "RERANK_API_BASE",                   // optional: pass-through from env below
        "-e", "RERANK_API_KEY",                    // optional: pass-through from env below
        "-e", "GITHUB_TOKEN",                      // optional: pass-through from env below
        "-e", "SYNC_ENABLED",                      // optional: pass-through from env below
        "-e", "SYNC_INTERVAL",                     // optional: pass-through from env below
        "n24q02m/wet-mcp:latest"
      ],
      "env": {
        // -- optional: LiteLLM Proxy (production, selfhosted gateway)
        // "LITELLM_PROXY_URL": "http://10.0.0.20:4000",
        // "LITELLM_PROXY_KEY": "sk-your-virtual-key",
        // -- optional: cloud embedding (Gemini > OpenAI > Cohere) + media analysis
        // -- without this, uses built-in local Qwen3-Embedding-0.6B + Qwen3-Reranker-0.6B (ONNX, CPU)
        "API_KEYS": "GOOGLE_API_KEY:AIza...",
        // -- optional: custom endpoints (e.g. modalcom-ai-workers on Modal.com)
        // "EMBEDDING_API_BASE": "https://your-worker.modal.run",
        // "EMBEDDING_API_KEY": "your-key",
        // "RERANK_API_BASE": "https://your-worker.modal.run",
        // "RERANK_API_KEY": "your-key",
        // -- optional: higher rate limits for docs discovery (60 -> 5000 req/hr)
        // -- auto-detected from `gh auth token` if GitHub CLI is installed
        // "GITHUB_TOKEN": "ghp_...",
        // -- optional: sync indexed docs across machines via rclone
        "SYNC_ENABLED": "true",                    // optional, default: false
        "SYNC_INTERVAL": "300"                     // optional, auto-sync every 5min (0 = manual only)
      }
    }
  }
}
```

### Pre-install (optional)

Pre-download all dependencies before adding to your MCP client config. This avoids slow first-run startup:

```bash
# Pre-download SearXNG, Playwright, embedding model (~570MB), and reranker model (~570MB)
uvx --python 3.13 wet-mcp warmup

# With cloud embedding (validates API key, skips local download if cloud works)
API_KEYS="GOOGLE_API_KEY:AIza..." uvx --python 3.13 wet-mcp warmup
```

### Sync setup

Sync is fully automatic. Just set `SYNC_ENABLED=true` and the server handles everything:

1. **First sync**: rclone is auto-downloaded, a browser opens for OAuth authentication
2. **Token saved**: OAuth token is stored locally at `~/.wet-mcp/tokens/` (600 permissions)
3. **Subsequent runs**: Token is loaded automatically — no manual steps needed

For non-Google Drive providers, set `SYNC_PROVIDER` and `SYNC_REMOTE`:

```jsonc
{
  "SYNC_ENABLED": "true",
  "SYNC_PROVIDER": "dropbox",        // rclone provider type
  "SYNC_REMOTE": "dropbox"           // rclone remote name
}
```

> **Advanced**: You can also run `uvx --python 3.13 wet-mcp setup-sync drive` to pre-authenticate before first use, but this is optional.

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
| `LITELLM_PROXY_URL` | - | LiteLLM Proxy URL (e.g. `http://10.0.0.20:4000`). Enables proxy mode |
| `LITELLM_PROXY_KEY` | - | LiteLLM Proxy virtual key (e.g. `sk-...`) |
| `API_KEYS` | - | LLM API keys for SDK mode (format: `ENV_VAR:key,...`) |
| `LLM_MODELS` | `gemini/gemini-3-flash-preview` | LiteLLM model for media analysis (optional) |
| `LLM_API_BASE` | - | Custom LLM endpoint URL (optional, for SDK mode) |
| `LLM_API_KEY` | - | Custom LLM endpoint key (optional) |
| `EMBEDDING_API_BASE` | - | Custom embedding endpoint URL (optional, for SDK mode) |
| `EMBEDDING_API_KEY` | - | Custom embedding endpoint key (optional) |
| `RERANK_API_BASE` | - | Custom rerank endpoint URL (optional, for SDK mode) |
| `RERANK_API_KEY` | - | Custom rerank endpoint key (optional) |
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
| `GITHUB_TOKEN` | - | GitHub personal access token for library discovery (optional, increases rate limit from 60 to 5000 req/hr). **Auto-detected** from `gh auth token` if GitHub CLI is installed and authenticated — no need to set manually. |
| `SYNC_ENABLED` | `false` | Enable rclone sync |
| `SYNC_PROVIDER` | `drive` | rclone provider type (drive, dropbox, s3, etc.) |
| `SYNC_REMOTE` | `gdrive` | rclone remote name |
| `SYNC_FOLDER` | `wet-mcp` | Remote folder name |
| `SYNC_INTERVAL` | `300` | Auto-sync interval in seconds (0=manual) |
| `LOG_LEVEL` | `INFO` | Logging level |

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

### LLM Configuration (3-Mode Architecture)

LLM access (for media analysis) supports 3 modes, resolved by priority:

| Priority | Mode | Config | Use case |
|:---------|:-----|:-------|:---------|
| 1 | **Proxy** | `LITELLM_PROXY_URL` + `LITELLM_PROXY_KEY` | Production (OCI VM, selfhosted gateway) |
| 2 | **SDK** | `API_KEYS` or custom `*_API_BASE` | Dev/local with direct API access |
| 3 | **Local** | Nothing needed | Offline, embedding/rerank only (no LLM) |

No cross-mode fallback — if proxy is configured but unreachable, calls fail (no silent fallback to direct API).

### SearXNG Configuration (2-Mode)

Web search is powered by [SearXNG](https://github.com/searxng/searxng), a privacy-respecting metasearch engine.

| Mode | Config | Description |
|:-----|:-------|:------------|
| **Embedded** (default) | `WET_AUTO_SEARXNG=true` | Auto-installs and manages SearXNG as subprocess. Zero config needed. |
| **External** | `WET_AUTO_SEARXNG=false` + `SEARXNG_URL=http://host:port` | Connects to pre-existing SearXNG instance (e.g. Docker container, shared server). |

**Embedded mode** is best for local development and single-user deployments. On first run, wet-mcp automatically downloads and configures SearXNG.

**External mode** is recommended when:
- Running in Docker (use a separate SearXNG container)
- Sharing a SearXNG instance across multiple services
- SearXNG is already deployed on your infrastructure

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

## Compatible With

[![Claude Desktop](https://img.shields.io/badge/Claude_Desktop-F9DC7C?logo=anthropic&logoColor=black)](#quick-start)
[![Claude Code](https://img.shields.io/badge/Claude_Code-000000?logo=anthropic&logoColor=white)](#quick-start)
[![Cursor](https://img.shields.io/badge/Cursor-000000?logo=cursor&logoColor=white)](#quick-start)
[![VS Code Copilot](https://img.shields.io/badge/VS_Code_Copilot-007ACC?logo=visualstudiocode&logoColor=white)](#quick-start)
[![Antigravity](https://img.shields.io/badge/Antigravity-4285F4?logo=google&logoColor=white)](#quick-start)
[![Gemini CLI](https://img.shields.io/badge/Gemini_CLI-8E75B2?logo=googlegemini&logoColor=white)](#quick-start)
[![OpenAI Codex](https://img.shields.io/badge/Codex-412991?logo=openai&logoColor=white)](#quick-start)
[![OpenCode](https://img.shields.io/badge/OpenCode-F7DF1E?logoColor=black)](#quick-start)

## Also by n24q02m

| Server | Description | Install |
|--------|-------------|---------|
| [better-notion-mcp](https://github.com/n24q02m/better-notion-mcp) | Notion API for AI agents | `npx -y @n24q02m/better-notion-mcp@latest` |
| [mnemo-mcp](https://github.com/n24q02m/mnemo-mcp) | Persistent AI memory with hybrid search | `uvx mnemo-mcp@latest` |
| [better-email-mcp](https://github.com/n24q02m/better-email-mcp) | Email (IMAP/SMTP) for AI agents | `npx -y @n24q02m/better-email-mcp@latest` |
| [better-godot-mcp](https://github.com/n24q02m/better-godot-mcp) | Godot Engine for AI agents | `npx -y @n24q02m/better-godot-mcp@latest` |

## Related Projects

- **[modalcom-ai-workers](https://github.com/n24q02m/modalcom-ai-workers)** — GPU-accelerated AI workers on Modal.com (embedding, reranking)
- **[qwen3-embed](https://github.com/n24q02m/qwen3-embed)** — Local embedding/reranking library used by wet-mcp

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md)

## License

MIT - See [LICENSE](LICENSE)
