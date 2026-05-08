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

<!-- BEGIN: AUTO-GENERATED-CROSS-PROMO -->
<details>
  <summary><strong>Sister projects from n24q02m</strong> (click to expand)</summary>

| Project | Tagline | Tag |
|---|---|---|
| [better-code-review-graph](https://github.com/n24q02m/better-code-review-graph) | Knowledge graph for token-efficient code reviews -- fixed search, configurabl... | MCP |
| [better-email-mcp](https://github.com/n24q02m/better-email-mcp) | IMAP/SMTP email server for AI agents -- 6 composite tools with multi-account ... | MCP |
| [better-godot-mcp](https://github.com/n24q02m/better-godot-mcp) | Composite MCP server for Godot Engine -- 17 mega-tools for AI-assisted game d... | MCP |
| [better-notion-mcp](https://github.com/n24q02m/better-notion-mcp) | Markdown-first Notion API server for AI agents -- 10 composite tools replacin... | MCP |
| [better-telegram-mcp](https://github.com/n24q02m/better-telegram-mcp) | MCP server for Telegram with dual-mode support: Bot API (httpx) for quick bot... | MCP |
| [claude-plugins](https://github.com/n24q02m/claude-plugins) | Full documentation: mcp.n24q02m.com — unified docs for all 8 servers + the mc... | Marketplace |
| [imagine-mcp](https://github.com/n24q02m/imagine-mcp) | Production-grade MCP server for image and video understanding + generation ac... | MCP |
| [jules-task-archiver](https://github.com/n24q02m/jules-task-archiver) | Chrome Extension for bulk operations on Jules tasks via batchexecute API -- a... | Tooling |
| [mcp-core](https://github.com/n24q02m/mcp-core) | Unified MCP Streamable HTTP 2025-11-25 transport, OAuth 2.1 Authorization Ser... | MCP |
| [mnemo-mcp](https://github.com/n24q02m/mnemo-mcp) | Persistent AI memory with hybrid search and embedded sync. Open, free, unlimi... | MCP |
| [qwen3-embed](https://github.com/n24q02m/qwen3-embed) | Lightweight Qwen3 text embedding and reranking via ONNX Runtime and GGUF | Library |
| [skret](https://github.com/n24q02m/skret) | Secrets without the server. | CLI |
| [web-core](https://github.com/n24q02m/web-core) | Shared web infrastructure package for search, scraping, HTTP security, and st... | Library |
| [wet-mcp](https://github.com/n24q02m/wet-mcp) | Open-source MCP Server for web search, content extraction, library docs & mul... | MCP |

</details>
<!-- END: AUTO-GENERATED-CROSS-PROMO -->


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

## Status

> **2026-05-02 -- Architecture stabilization update**
>
> Past months saw significant churn around credential handling and the daemon-bridge auto-spawn pattern. This caused multi-process races, browser tab spam, and inconsistent setup UX across plugins. **As of v&lt;auto&gt;, the architecture is stable**: 2 clean modes (stdio + HTTP), no daemon-bridge layer, no auto-spawn from stdio.
>
> Apologies for the instability period. If you encountered issues with prior versions, please update to v&lt;auto&gt;+ and follow the current `docs/setup-manual.md` -- most prior workarounds are no longer needed.
>
> **Related plugins from the same author**:
> - [wet-mcp](https://github.com/n24q02m/wet-mcp) -- Web search + content extraction
> - [mnemo-mcp](https://github.com/n24q02m/mnemo-mcp) -- Persistent AI memory
> - [imagine-mcp](https://github.com/n24q02m/imagine-mcp) -- Image/video understanding + generation
> - [better-notion-mcp](https://github.com/n24q02m/better-notion-mcp) -- Notion API
> - [better-email-mcp](https://github.com/n24q02m/better-email-mcp) -- Email management
> - [better-telegram-mcp](https://github.com/n24q02m/better-telegram-mcp) -- Telegram
> - [better-godot-mcp](https://github.com/n24q02m/better-godot-mcp) -- Godot Engine
> - [better-code-review-graph](https://github.com/n24q02m/better-code-review-graph) -- Code review knowledge graph
>
> All plugins share the same architecture (this spec) -- install once, learn pattern transfers.

## Documentation

Full docs at **[mcp.n24q02m.com/servers/wet-mcp/](https://mcp.n24q02m.com/servers/wet-mcp/)**:

- [Setup](https://mcp.n24q02m.com/servers/wet-mcp/setup/) -- install methods for Claude Code, Codex, Gemini CLI, Cursor, Windsurf, mcp.json
- [Modes overview](https://mcp.n24q02m.com/get-started/modes-overview/) -- stdio / local-relay / remote-relay / remote-oauth
- [Multi-user setup](https://mcp.n24q02m.com/get-started/multi-user/) -- per-JWT-sub credential model

**Install with AI agent** -- paste this to your AI coding agent:

> Install MCP server `wet-mcp` following the steps at
> https://raw.githubusercontent.com/n24q02m/claude-plugins/main/plugins/wet-mcp/setup-with-agent.md

## Tools

| Tool | Actions | Description |
|:-----|:--------|:------------|
| `search` | `search`, `research`, `docs`, `similar` | Web search (with filters, reranking, expand/enrich), academic research, library docs (HyDE), find similar |
| `extract` | `extract`, `batch`, `crawl`, `map`, `convert`, `extract_structured` | Content extraction, batch processing (up to 50 URLs), deep crawling, site mapping, local file conversion, structured data extraction (JSON Schema) |
| `media` | `list`, `download`, `analyze` | Media discovery, download, and analysis |
| `config` | `status`, `set`, `cache_clear`, `docs_reindex` | Server configuration and cache management |
| `setup` | `open_relay`, `status`, `skip`, `reset`, `complete`, `warmup`, `setup_sync` | Credential setup (browser relay, local-only mode, reset), status check, model warmup, Google Drive sync |
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

## Trust Model

This plugin implements **TC-Local** (machine-bound, single trust principal). See [mcp-core/docs/TRUST-MODEL.md](https://github.com/n24q02m/mcp-core/blob/main/docs/TRUST-MODEL.md) for full classification.

| Mode | Storage | Encryption | Who can read your data? |
|---|---|---|---|
| stdio (default) | `~/.wet-mcp/config.json` | AES-GCM, machine-bound key | Only your OS user (file perm 0600) |
| HTTP self-host | Same as stdio | Same | Only you (admin = user) |

## License

MIT -- See [LICENSE](LICENSE).