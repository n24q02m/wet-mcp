# WET MCP Server - Help

Welcome to **WET** (Web Extended Toolkit) MCP Server.

## Which Tool Should I Use?

| I want to... | Use this tool | Example |
|:-------------|:-------------|:--------|
| **Find** information on a topic | `search` | `search(action="search", query="python async patterns")` |
| **Read** full content from a URL | `extract` | `extract(action="extract", urls=["https://example.com/article"])` |
| **Look up** library documentation | `search` (docs) | `search(action="docs", query="routing", library="fastapi")` |
| **Download** images/videos/audio | `media` | `media(action="list", url="https://example.com/gallery")` |
| **Convert** a local file to text | `extract` (convert) | `extract(action="convert", paths=["/home/user/report.pdf"])` |
| **Check** server status/settings | `config` | `config(action="status")` |
| **Warmup** models and deps | `config` | `config(action="warmup")` |
| **Setup** cloud sync | `config` | `config(action="setup_sync")` |

**Key distinction**: `search` returns result listings (titles, URLs, snippets). `extract` returns full page content. Use `search` to find URLs, then `extract` to read them.

## Available Tools

| Tool | Purpose |
|:-----|:--------|
| `search` | Find information: web search, academic research, library docs search |
| `extract` | Read content: extract from URLs, crawl sites, map structure, convert local files |
| `media` | Media files: discover, download, and analyze images/videos/audio |
| `config` | Server management: status, settings, cache, re-indexing, warmup, sync setup |
| `help` | Get full documentation for any tool |

## Quick Reference

### search tool

```json
// Web search -- returns result listings (titles, URLs, snippets)
{"action": "search", "query": "your search query"}

// Academic/scientific search (Google Scholar, arXiv, PubMed)
{"action": "research", "query": "transformer attention mechanism"}

// Search library documentation (auto-indexes on first call)
{"action": "docs", "query": "how to create routes", "library": "fastapi"}

// Find pages similar to a URL
{"action": "similar", "query": "https://example.com/interesting-article"}
```

### extract tool

```json
// Read full content from a URL -- returns page text in markdown
{"action": "extract", "urls": ["https://example.com/article"]}

// Read as plain text
{"action": "extract", "urls": ["https://example.com"], "format": "text"}

// Deep crawl following links
{"action": "crawl", "urls": ["https://docs.example.com"], "depth": 2}

// Map site structure (URLs only, no content)
{"action": "map", "urls": ["https://example.com"]}

// Convert local files to markdown
{"action": "convert", "paths": ["/home/user/report.pdf"]}
```

### media tool

```json
// Discover media on a page
{"action": "list", "url": "https://example.com/gallery", "media_type": "images"}

// Download specific files
{"action": "download", "media_urls": ["https://example.com/image.png"]}

// Analyze media with LLM (requires API_KEYS)
{"action": "analyze", "url": "/path/to/image.jpg", "prompt": "Describe this image"}
```

### config tool

```json
// Show server status
{"action": "status"}

// Clear web cache
{"action": "cache_clear"}

// Force re-index a library
{"action": "docs_reindex", "key": "fastapi"}

// Update a setting
{"action": "set", "key": "log_level", "value": "DEBUG"}

// Warmup models and dependencies
{"action": "warmup"}

// Configure cloud sync
{"action": "setup_sync"}

// Setup: open browser to configure API keys
{"action": "setup_open_relay"}

// Setup: show credential state
{"action": "setup_status"}

// Setup: use local models only (no cloud)
{"action": "setup_skip"}

// Setup: clear credentials and reset
{"action": "setup_reset"}

// Setup: re-resolve credentials from environment
{"action": "setup_complete"}
```

## Getting Full Documentation

Call `help` with the tool name:

```json
{"tool_name": "search"}   // Search tool documentation
{"tool_name": "extract"}  // Extract tool documentation
{"tool_name": "media"}    // Media tool documentation
{"tool_name": "config"}   // Config tool documentation (includes warmup + sync setup)
```

## Features

- **Auto-setup**: First run automatically installs Playwright and configures SearXNG
- **Anti-bot bypass**: Stealth mode works with Cloudflare, Medium, LinkedIn, etc.
- **Multimodal**: Extract and download images, videos, audio files
- **Deep crawling**: Follow links to specified depth with page limits
- **Academic search**: Google Scholar, Semantic Scholar, arXiv, PubMed, CrossRef, BASE
- **Library docs**: Auto-discover and index documentation with FTS5 hybrid search
- **Local cache**: TTL-based caching for all web operations (search, extract, crawl, map)
- **Docs sync**: Sync indexed docs across machines via rclone
