# web Tool Documentation

Web operations: search, extract, crawl, map, research, docs.

## Actions

### search
Web search via SearXNG metasearch engine.

**Parameters:**
- `query` (required): Search query string
- `categories`: Search category - general, images, videos, files (default: general)
- `max_results`: Maximum results to return (default: 10)

**Example:**
```json
{"action": "search", "query": "python web scraping tutorial", "max_results": 5}
```

---

### extract
Get clean content from one or more URLs.

**Parameters:**
- `urls` (required): List of URLs to extract
- `format`: Output format - markdown, text, html (default: markdown)
- `stealth`: Enable stealth mode to bypass anti-bot (default: true)

**Example:**
```json
{"action": "extract", "urls": ["https://example.com/article"]}
```

---

### crawl
Deep crawl starting from root URLs.

**Parameters:**
- `urls` (required): List of root URLs to crawl from
- `depth`: How many levels deep to crawl (default: 2)
- `max_pages`: Maximum pages to crawl (default: 20)
- `format`: Output format (default: markdown)
- `stealth`: Enable stealth mode (default: true)

**Example:**
```json
{"action": "crawl", "urls": ["https://docs.example.com"], "depth": 3}
```

---

### map
Discover site structure without extracting content.

**Parameters:**
- `urls` (required): List of root URLs
- `depth`: Discovery depth (default: 2)
- `max_pages`: Maximum URLs to discover (default: 50)

**Example:**
```json
{"action": "map", "urls": ["https://example.com"]}
```

---

### research
Academic and scientific search using SearXNG science engines (Google Scholar, Semantic Scholar, arXiv, PubMed, CrossRef, BASE).

**Parameters:**
- `query` (required): Research query string
- `max_results`: Maximum results to return (default: 10)

**Example:**
```json
{"action": "research", "query": "transformer attention mechanism", "max_results": 5}
```

**Returns:** Results include source_type (arxiv, google_scholar, semantic_scholar, pubmed, doi, academic).

---

### docs
Search library/framework documentation with auto-indexing. First call indexes docs into local FTS5 database; subsequent calls use cached index for instant results.

**Parameters:**
- `query` (required): What to search for in docs
- `library` (required): Library name (e.g., "react", "fastapi", "pytorch")
- `language`: Programming language for disambiguation (e.g., "python", "java", "rust")
- `version`: Specific version (default: latest)
- `limit`: Maximum results (default: 10)

**Discovery order:** llms.txt > npm/PyPI/crates.io registry > SearXNG fallback > Crawl4AI fetch.

**Example:**
```json
{"action": "docs", "query": "how to create a router", "library": "fastapi"}
```

**Returns:** Relevant documentation chunks with title, content, URL, and relevance score.

---

## Anti-Bot Features

The `stealth` parameter enables:
- Stealth mode: Masks navigator.webdriver, emulates plugins
- Undetected browser: For advanced detection (Cloudflare, Datadome)

## Caching

When `WET_CACHE=true` (default), all actions cache results locally:
- search/research: 1 hour TTL
- extract/crawl/map: 1 day TTL
- docs: Persistent FTS5 index (no TTL)
