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
- **Sync** -- Cross-machine sync of indexed docs via Google Drive (OAuth Device Code, no browser redirect)

## Setup

**With AI Agent** -- copy and send this to your AI agent:

> Please set up wet-mcp for me. Follow this guide:
> https://raw.githubusercontent.com/n24q02m/wet-mcp/main/docs/setup-with-agent.md

**Manual Setup** -- follow [docs/setup-manual.md](docs/setup-manual.md)

## Tools

| Tool | Actions | Description |
|:-----|:--------|:------------|
| `search` | `search`, `research`, `docs`, `similar` | Web search (with filters, reranking, expand/enrich), academic research, library docs (HyDE), find similar |
| `extract` | `extract`, `batch`, `crawl`, `map`, `convert`, `extract_structured` | Content extraction, batch processing (up to 50 URLs), deep crawling, site mapping, local file conversion, structured data extraction (JSON Schema) |
| `media` | `list`, `download`, `analyze` | Media discovery, download, and analysis |
| `config` | `status`, `set`, `cache_clear`, `docs_reindex` | Server configuration and cache management |
| `setup` | `warmup`, `setup_sync`, `setup_relay` | Pre-download models, configure cloud sync, relay setup |
| `help` | -- | Full documentation for any tool |

## Security

- **SSRF prevention** -- URL validation on crawl targets
- **Graceful fallbacks** -- Cloud → Local embedding, multi-tier crawling
- **Error sanitization** -- No credentials in error messages
- **File conversion sandboxing** -- Optional `CONVERT_ALLOWED_DIRS` restriction

## Build from Source

```bash
git clone https://github.com/n24q02m/wet-mcp.git
cd wet-mcp
uv sync
uv run wet-mcp
```

## License

MIT -- See [LICENSE](LICENSE).
