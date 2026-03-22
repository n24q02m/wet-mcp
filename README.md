# WET - Web Extended Toolkit MCP Server

mcp-name: io.github.n24q02m/wet-mcp

**Open-source MCP Server for web search, content extraction, library docs & multimodal analysis.**

<!-- Badge Row 1: Status -->
[![CI](https://github.com/n24q02m/wet-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/n24q02m/wet-mcp/actions/workflows/ci.yml)
[![codecov](https://codecov.io/gh/n24q02m/wet-mcp/graph/badge.svg?token=JK19TRLPEX)](https://codecov.io/gh/n24q02m/wet-mcp)
[![PyPI](https://img.shields.io/pypi/v/wet-mcp?logo=pypi&logoColor=white)](https://pypi.org/project/wet-mcp/)
[![Docker](https://img.shields.io/docker/v/n24q02m/wet-mcp?label=docker&logo=docker&logoColor=white&sort=semver)](https://hub.docker.com/r/n24q02m/wet-mcp)
[![License: MIT](https://img.shields.io/github/license/n24q02m/wet-mcp)](LICENSE)

<!-- Badge Row 2: Tech -->
[![Python](https://img.shields.io/badge/Python-3776AB?logo=python&logoColor=white)](#)
[![SearXNG](https://img.shields.io/badge/SearXNG-3050FF?logo=searxng&logoColor=white)](#)
[![MCP](https://img.shields.io/badge/MCP-000000?logo=anthropic&logoColor=white)](#)
[![semantic-release](https://img.shields.io/badge/semantic--release-e10079?logo=semantic-release&logoColor=white)](https://github.com/python-semantic-release/python-semantic-release)
[![Renovate](https://img.shields.io/badge/renovate-enabled-1A1F6C?logo=renovatebot&logoColor=white)](https://developer.mend.io/)

<a href="https://glama.ai/mcp/servers/n24q02m/wet-mcp">
  <img width="380" height="200" src="https://glama.ai/mcp/servers/n24q02m/wet-mcp/badge" alt="WET MCP server" />
</a>

## Features

- **Web Search** -- Embedded SearXNG metasearch (Google, Bing, DuckDuckGo, Brave) with filters, semantic reranking, query expansion, and snippet enrichment
- **Academic Research** -- Search Google Scholar, Semantic Scholar, arXiv, PubMed, CrossRef, BASE
- **Library Docs** -- Auto-discover and index documentation with FTS5 hybrid search, HyDE-enhanced retrieval, and version-specific docs
- **Content Extract** -- Clean content extraction (Markdown/Text), structured data extraction (LLM + JSON Schema), batch processing (up to 50 URLs), deep crawling, site mapping
- **Local File Conversion** -- Convert PDF, DOCX, XLSX, CSV, HTML, EPUB, PPTX to Markdown
- **Media** -- List, download, and analyze images, videos, audio files
- **Anti-bot** -- Stealth mode bypasses Cloudflare, Medium, LinkedIn, Twitter
- **Zero Config** -- Built-in local Qwen3 embedding + reranking, no API keys needed. Optional cloud providers (Jina AI, Gemini, OpenAI, Cohere)
- **Sync** -- Cross-machine sync of indexed docs via rclone (Google Drive, S3, Dropbox)

## Quick Start

### Claude Code Plugin (Recommended)

```bash
claude plugin add n24q02m/wet-mcp
```

### MCP Server

> **Python 3.13 required** -- Python 3.14+ is **not** supported due to SearXNG incompatibility. You **must** specify `--python 3.13` when using `uvx`.

**On first run**, the server automatically installs SearXNG, Playwright chromium, and starts the embedded search engine.

#### Option 1: uvx

```jsonc
{
  "mcpServers": {
    "wet": {
      "command": "uvx",
      "args": ["--python", "3.13", "wet-mcp@latest"],
      "env": {
        // -- optional: cloud embedding + reranking (Jina AI recommended)
        "API_KEYS": "JINA_AI_API_KEY:jina_...",
        // -- or: "API_KEYS": "GOOGLE_API_KEY:AIza...,COHERE_API_KEY:co-...",
        // -- without API_KEYS, uses built-in local Qwen3 ONNX models (CPU, ~570MB first download)
        // -- optional: LiteLLM Proxy (production, selfhosted gateway)
        // "LITELLM_PROXY_URL": "http://10.0.0.20:4000",
        // "LITELLM_PROXY_KEY": "sk-your-virtual-key",
        // -- optional: higher rate limits for docs discovery (60 -> 5000 req/hr)
        "GITHUB_TOKEN": "ghp_...",
        // -- optional: restrict local file conversion to specific directories
        // "CONVERT_ALLOWED_DIRS": "/home/user/docs,/tmp/uploads",
        // -- optional: sync indexed docs across machines via rclone
        "SYNC_ENABLED": "true",                    // default: false
        "SYNC_INTERVAL": "300"                     // auto-sync every 5min (0 = manual only)
      }
    }
  }
}
```

#### Option 2: Docker

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
        "-e", "SYNC_INTERVAL",
        "n24q02m/wet-mcp:latest"
      ],
      "env": {
        "API_KEYS": "JINA_AI_API_KEY:jina_...",
        "GITHUB_TOKEN": "ghp_...",
        "SYNC_ENABLED": "true",
        "SYNC_INTERVAL": "300"
      }
    }
  }
}
```

### Pre-install (optional)

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
3. **Subsequent runs**: Token is loaded automatically -- no manual steps needed

For non-Google Drive providers, set `SYNC_PROVIDER` and `SYNC_REMOTE`:

```jsonc
{
  "SYNC_ENABLED": "true",
  "SYNC_PROVIDER": "dropbox",
  "SYNC_REMOTE": "dropbox"
}
```

## Tools

| Tool | Actions | Description |
|:-----|:--------|:------------|
| `search` | `search`, `research`, `docs`, `similar` | Web search (with filters, reranking, expand/enrich), academic research, library docs (HyDE), find similar |
| `extract` | `extract`, `batch`, `crawl`, `map`, `convert`, `extract_structured` | Content extraction, batch processing (up to 50 URLs), deep crawling, site mapping, local file conversion, structured data extraction (JSON Schema) |
| `media` | `list`, `download`, `analyze` | Media discovery, download, and analysis |
| `config` | `status`, `set`, `cache_clear`, `docs_reindex` | Server configuration and cache management |
| `help` | -- | Full documentation for any tool |

## Configuration

| Variable | Required | Default | Description |
|:---------|:---------|:--------|:------------|
| `API_KEYS` | No | -- | LLM API keys for SDK mode (format: `ENV_VAR:key,...`). Enables cloud embedding + reranking |
| `LITELLM_PROXY_URL` | No | -- | LiteLLM Proxy URL. Enables proxy mode |
| `LITELLM_PROXY_KEY` | No | -- | LiteLLM Proxy virtual key |
| `GITHUB_TOKEN` | No | auto-detect | GitHub token for docs discovery (60 -> 5000 req/hr). Auto-detected from `gh auth token` |
| `EMBEDDING_BACKEND` | No | auto-detect | `litellm` (cloud) or `local` (Qwen3). Auto: API_KEYS -> litellm, else local |
| `EMBEDDING_MODEL` | No | auto-detect | LiteLLM embedding model name |
| `EMBEDDING_DIMS` | No | `0` (auto=768) | Embedding dimensions |
| `RERANK_ENABLED` | No | `true` | Enable reranking after search |
| `RERANK_BACKEND` | No | auto-detect | `litellm` or `local`. Auto: Cohere/Jina key -> litellm, else local |
| `RERANK_MODEL` | No | auto-detect | LiteLLM rerank model name |
| `RERANK_TOP_N` | No | `10` | Return top N results after reranking |
| `LLM_MODELS` | No | `gemini/gemini-3-flash-preview` | LiteLLM model for media analysis |
| `WET_AUTO_SEARXNG` | No | `true` | Auto-start embedded SearXNG subprocess |
| `WET_SEARXNG_PORT` | No | `41592` | SearXNG port |
| `SEARXNG_URL` | No | `http://localhost:41592` | External SearXNG URL (when auto disabled) |
| `SEARXNG_TIMEOUT` | No | `30` | SearXNG request timeout in seconds |
| `CONVERT_MAX_FILE_SIZE` | No | `104857600` | Max file size for local conversion in bytes (100MB) |
| `CONVERT_ALLOWED_DIRS` | No | -- | Comma-separated paths to restrict local file conversion |
| `CACHE_DIR` | No | `~/.wet-mcp` | Data directory for cache, docs, downloads |
| `DOCS_DB_PATH` | No | `~/.wet-mcp/docs.db` | Docs database location |
| `DOWNLOAD_DIR` | No | `~/.wet-mcp/downloads` | Media download directory |
| `TOOL_TIMEOUT` | No | `120` | Tool execution timeout in seconds (0=no timeout) |
| `WET_CACHE` | No | `true` | Enable/disable web cache |
| `SYNC_ENABLED` | No | `false` | Enable rclone sync |
| `SYNC_PROVIDER` | No | `drive` | rclone provider type (drive, dropbox, s3, etc.) |
| `SYNC_REMOTE` | No | `gdrive` | rclone remote name |
| `SYNC_FOLDER` | No | `wet-mcp` | Remote folder name |
| `SYNC_INTERVAL` | No | `300` | Auto-sync interval in seconds (0=manual) |
| `LOG_LEVEL` | No | `INFO` | Logging level |

### Embedding & Reranking

Both embedding and reranking are **always available** -- local models are built-in and require no configuration.

- **Jina AI (recommended)**: A single `JINA_AI_API_KEY` enables both embedding and reranking
- **Embedding priority**: Jina AI > Gemini > OpenAI > Cohere. Local Qwen3 fallback always available
- **Reranking priority**: Jina AI > Cohere. Local Qwen3 fallback always available
- **GPU auto-detection**: CUDA/DirectML auto-detected, uses GGUF models for better performance
- All embeddings stored at **768 dims**. Switching providers never breaks the vector table

### LLM Configuration (3-Mode Architecture)

| Priority | Mode | Config | Use case |
|:---------|:-----|:-------|:---------|
| 1 | **Proxy** | `LITELLM_PROXY_URL` + `LITELLM_PROXY_KEY` | Production (selfhosted gateway) |
| 2 | **SDK** | `API_KEYS` | Dev/local with direct API access |
| 3 | **Local** | Nothing needed | Offline, embedding/rerank only (no LLM) |

### SearXNG Configuration (2-Mode)

| Mode | Config | Description |
|:-----|:-------|:------------|
| **Embedded** (default) | `WET_AUTO_SEARXNG=true` | Auto-installs and manages SearXNG as subprocess |
| **External** | `WET_AUTO_SEARXNG=false` + `SEARXNG_URL=http://host:port` | Connects to pre-existing SearXNG instance |

## Build from Source

```bash
git clone https://github.com/n24q02m/wet-mcp.git
cd wet-mcp
uv sync
uv run wet-mcp
```

## Compatible With

[![Claude Code](https://img.shields.io/badge/Claude_Code-000000?logo=anthropic&logoColor=white)](#quick-start)
[![Claude Desktop](https://img.shields.io/badge/Claude_Desktop-F9DC7C?logo=anthropic&logoColor=black)](#quick-start)
[![Cursor](https://img.shields.io/badge/Cursor-000000?logo=cursor&logoColor=white)](#quick-start)
[![VS Code Copilot](https://img.shields.io/badge/VS_Code_Copilot-007ACC?logo=visualstudiocode&logoColor=white)](#quick-start)
[![Antigravity](https://img.shields.io/badge/Antigravity-4285F4?logo=google&logoColor=white)](#quick-start)
[![Gemini CLI](https://img.shields.io/badge/Gemini_CLI-8E75B2?logo=googlegemini&logoColor=white)](#quick-start)
[![OpenAI Codex](https://img.shields.io/badge/Codex-412991?logo=openai&logoColor=white)](#quick-start)
[![OpenCode](https://img.shields.io/badge/OpenCode-F7DF1E?logoColor=black)](#quick-start)

## Also by n24q02m

| Server | Description |
|:-------|:------------|
| [mnemo-mcp](https://github.com/n24q02m/mnemo-mcp) | Persistent AI memory with hybrid search and embedded sync |
| [better-notion-mcp](https://github.com/n24q02m/better-notion-mcp) | Enhanced Notion API integration with 9 composite tools |
| [better-email-mcp](https://github.com/n24q02m/better-email-mcp) | Email management via IMAP/SMTP |
| [better-telegram-mcp](https://github.com/n24q02m/better-telegram-mcp) | Telegram Bot API + MTProto for AI agents |
| [better-godot-mcp](https://github.com/n24q02m/better-godot-mcp) | Godot Engine for AI agents |

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

MIT -- See [LICENSE](LICENSE).
