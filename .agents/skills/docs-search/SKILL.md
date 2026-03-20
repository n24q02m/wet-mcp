---
name: docs-search
description: Search library/framework documentation using wet-mcp cached indexing
argument-hint: "[library] [query]"
---

# Documentation Search

Search library and framework documentation efficiently using wet-mcp's extraction and caching.

## Steps

1. **Identify the library** and what specifically needs to be found (API reference, guide, example, changelog).

2. **Search documentation** using the `search` MCP tool:
   - `search(action="search", query="[library] [specific topic]", search_type="docs")`
   - If docs search type is not specific enough, use web search with site filter

3. **Extract documentation page** using the `extract` MCP tool:
   - `extract(action="extract", url="[docs-url]", mode="markdown")` for full page content
   - Use `extract(action="extract", url="[docs-url]", mode="links")` to discover related pages

4. **Navigate documentation structure**:
   - Use `extract(action="sitemap", url="[docs-root]")` to map the full documentation site
   - Follow links to related sections as needed

5. **Present findings**:
   - Quote relevant code examples from docs
   - Link to source documentation pages
   - Note version-specific information

## When to Use

- Looking up API usage for a specific library
- Finding configuration options or migration guides
- Discovering best practices from official documentation
- Checking version compatibility or changelog entries
