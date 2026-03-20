---
name: deep-research
description: Multi-source research workflow using wet-mcp for comprehensive topic investigation
argument-hint: "[topic]"
---

# Deep Research

Multi-source research workflow: search -> extract top results -> cross-reference academic -> synthesize with citations.

## Steps

1. **Define research scope** by asking the user for the topic and any specific angles or constraints.

2. **Web search** using the `search` MCP tool with action `search`:
   - Run 2-3 queries with different phrasings
   - Include an academic search: `search(action="search", query="topic", search_type="academic")`

3. **Extract key sources** using the `extract` MCP tool:
   - Extract top 3-5 most relevant URLs from search results
   - Use `extract(action="extract", url="...", mode="markdown")` for full content

4. **Cross-reference findings**:
   - Identify common claims across sources
   - Note contradictions or gaps
   - Track citation sources

5. **Synthesize report**:
   - Present findings organized by theme
   - Include inline citations [Source Title](URL)
   - Highlight confidence levels (well-supported vs single-source claims)
   - Note gaps in available information

## When to Use

- Researching unfamiliar topics before implementation
- Evaluating technology choices with evidence
- Fact-checking claims or assumptions
- Literature reviews for technical decisions
