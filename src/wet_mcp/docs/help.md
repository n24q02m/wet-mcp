# WET MCP Server - Help

Welcome to **WET** (Web Extended Toolkit) MCP Server.

## Available Tools

| Tool | Description |
|:-----|:------------|
| `search` | Web search, academic research, library documentation search |
| `extract` | Content extraction, deep crawling, site mapping |
| `media` | Media discovery (images, videos, audio) and download |
| `help` | Get full documentation for any tool |

## Quick Reference

### search tool

```json
// Search the web
{"action": "search", "query": "your search query"}

// Academic/scientific search
{"action": "research", "query": "transformer attention mechanism"}

// Search library documentation (auto-indexes on first call)
{"action": "docs", "query": "how to create routes", "library": "fastapi"}
```

### extract tool

```json
// Extract content from URLs
{"action": "extract", "urls": ["https://example.com"]}

// Crawl multiple pages
{"action": "crawl", "urls": ["https://docs.example.com"], "depth": 2}

// Map site structure
{"action": "map", "urls": ["https://example.com"]}
```

### media tool

```json
// List media on a page
{"action": "list", "url": "https://example.com"}

// Download specific files
{"action": "download", "media_urls": ["https://example.com/image.png"]}

// Analyze media with LLM (requires API_KEYS)
{"action": "analyze", "url": "/path/to/image.jpg", "prompt": "Describe this image"}
```

## Getting Full Documentation

Call `help` with the tool name:

```json
{"tool_name": "search"}   // Search tool documentation
{"tool_name": "extract"}  // Extract tool documentation
{"tool_name": "media"}    // Media tool documentation
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
