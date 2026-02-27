# Style Guide - wet-mcp

## Architecture
Web extraction and search MCP server. Python, single-package repo.

## Python
- Formatter/Linter: Ruff (default config)
- Type checker: ty
- Test: pytest + pytest-asyncio
- Package manager: uv
- SDK: mcp[cli]
- Core deps: httpx, beautifulsoup4, SearXNG (bundled)

## Code Patterns
- Async/await with httpx.AsyncClient for all HTTP operations
- SearXNG subprocess management for search
- Crawler with configurable depth/breadth and concurrent processing
- DocsDB with SQLite + FTS5 for documentation indexing
- Media download with SSRF protection (validate redirects, block internal IPs)
- Streaming downloads for large media files

## Commits
Conventional Commits (feat:, fix:, chore:, docs:, refactor:, test:).

## Security
SSRF prevention in all HTTP operations. Validate URLs and redirect targets. Bound crawler resources. Prevent arbitrary file writes via media tool.
