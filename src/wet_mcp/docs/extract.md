# extract Tool Documentation

Extract content from web pages, crawl sites, or map site structure.

## Actions

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

## Caching

When `WET_CACHE=true` (default), all extraction results are cached locally:
- extract/crawl/map: 1 day TTL
