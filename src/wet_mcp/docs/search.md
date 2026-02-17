# search Tool Documentation

Search the web, academic papers, or library documentation.

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
- `language`: Programming language for disambiguation (e.g., "python", "java", "rust"). Guides which registries to search and improves discovery for cross-language names. Supports: python/py, javascript/js/ts, rust/rs, go/golang, java, kotlin, csharp/c#, php, ruby, swift, c, cpp/c++, zig, dart, elixir, haskell, scala, and more.
- `version`: Specific version (default: latest)
- `limit`: Maximum results (default: 10)

**Discovery order:** llms.txt > npm/PyPI/crates.io registry > SearXNG fallback > Crawl4AI fetch.

**When to specify `language`:**
- Cross-language name collisions: "redis" (Python vs Node.js), "protobuf" (Python vs JS)
- Languages without registry: Java, C#, PHP, Ruby, C/C++, Swift, Zig
- Tools and system packages: "cmake", "boost", "openssl"

**Example:**
```json
{"action": "docs", "query": "how to create a router", "library": "fastapi"}
{"action": "docs", "query": "dependency injection", "library": "spring-boot", "language": "java"}
{"action": "docs", "query": "entity framework migrations", "library": "efcore", "language": "csharp"}
```

**Returns:** Relevant documentation chunks with title, content, URL, and relevance score.

---

## Caching

When `WET_CACHE=true` (default), search and research results are cached locally:
- search/research: 1 hour TTL
- docs: Persistent FTS5 index (no TTL)
