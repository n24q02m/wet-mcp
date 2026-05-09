# extract Tool Documentation

Extract content from web pages, crawl sites, or map site structure.

## Actions

### extract
Get clean content from one or more URLs. Powered by web-core's `ScrapingAgent`
escalation chain (`basic_http` -> `tls_spoof` -> `headless`) with cache-recommended
ordering and LLM selector inference fallback.

**Parameters:**
- `urls` (required): List of URLs to extract
- `format`: Reserved for backward compat (smart chunks always emit both `markdown` and `clean_text`)
- `stealth`: Forwarded to the headless strategy when the agent is built (default: true)

**Example:**
```json
{"action": "extract", "urls": ["https://example.com/article"]}
```

**Smart chunks output (per URL):**

```json
{
  "url": "https://example.com/article",
  "clean_text": "Article body without HTML tags or markdown decorators",
  "markdown": "# Title\n\nBody...",
  "structured_data": [{"@type": "Article", "headline": "..."}],
  "code_blocks": [{"lang": "python", "code": "x = 1"}],
  "metadata": {
    "title": "Page title (HTML <title> or first H1)",
    "url": "https://example.com/article",
    "scrape_strategy_used": "basic_http",
    "latency_ms": 412.0,
    "content_length": 14523,
    "source_format": "html",
    "headings": [{"level": "1", "text": "Title"}, {"level": "2", "text": "Sub"}]
  }
}
```

`structured_data` contains all `<script type="application/ld+json">` blobs (JSON-LD).
`code_blocks` lists every fenced code block in the markdown rendition with detected
language hint (`plain` when none).

PDF/DOCX/PPTX/XLSX URLs bypass the agent and use the markitdown bridge directly,
returning the legacy `{url, title, content, converter}` shape.

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
- `max_pages`: Maximum URLs to discover (default: 20)

**Example:**
```json
{"action": "map", "urls": ["https://example.com"]}
```

---

### convert
Convert local files to Markdown. Supports: PDF, DOCX, PPTX, XLSX, CSV, JSON, XML, HTML, EPUB, TXT, images (EXIF metadata).

**Parameters:**
- `paths` (required): List of absolute file paths (max 10)

**Example:**
```json
{"action": "convert", "paths": ["/home/user/report.pdf", "/home/user/data.xlsx"]}
```

**Security:** Paths are validated against traversal attacks, symlink escapes, and optional directory allowlist (`CONVERT_ALLOWED_DIRS` env var). Max file size: 100MB (configurable via `CONVERT_MAX_FILE_SIZE`).

---

### batch
Batch extract content from multiple URLs with per-domain rate limiting. Polite crawling: max 2 concurrent per domain, 1 req/s per domain, 10 global concurrent. Returns partial results on failure.

**Parameters:**
- `urls` (required): List of URLs (max 50)
- `format`: Output format (default: markdown)
- `stealth`: Enable stealth mode (default: false)

**Example:**
```json
{"action": "batch", "urls": ["https://a.com/1", "https://a.com/2", "https://b.com/1", ...]}
```

**Returns:** `{results: [...], errors: [...], summary: {total, success, failed}}`

---

### extract_structured
Extract structured data from web pages using LLM + JSON Schema. Provide a schema defining the data structure you want, and the LLM extracts matching data from the page content.

**Parameters:**
- `urls` (required): List of URLs to extract from
- `schema` (required): JSON Schema dict defining the expected output structure
- `prompt`: Additional instructions for the LLM (optional)
- `stealth`: Enable stealth mode (default: false)

**Example:**
```json
{
  "action": "extract_structured",
  "urls": ["https://example.com/pricing"],
  "schema": {
    "type": "object",
    "properties": {
      "plans": {
        "type": "array",
        "items": {
          "type": "object",
          "properties": {
            "name": {"type": "string"},
            "price": {"type": "string"},
            "features": {"type": "array", "items": {"type": "string"}}
          }
        }
      }
    }
  },
  "prompt": "Extract all pricing plans with their features"
}
```

**Returns:** `{data: <extracted>, urls: [...]}` or `{data: <extracted>, validation_warning: "...", urls: [...]}` if schema validation fails partially.

**Requires:** LLM (proxy or SDK mode). Returns error in local-only mode.

---

## Anti-Bot Features

The `stealth` parameter enables:
- Stealth mode: Masks navigator.webdriver, emulates plugins
- Undetected browser: For advanced detection (Cloudflare, Datadome)

## Caching

When `WET_CACHE=true` (default), all extraction results are cached locally:
- extract/crawl/map: 1 day TTL
