# web Tool Documentation

Web operations: search, extract, crawl, map.

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

## Anti-Bot Features

The `stealth` parameter enables:
- Stealth mode: Masks navigator.webdriver, emulates plugins
- Undetected browser: For advanced detection (Cloudflare, Datadome)
