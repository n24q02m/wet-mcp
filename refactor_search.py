import sys

file_path = "src/wet_mcp/server.py"
with open(file_path, "r") as f:
    lines = f.readlines()

start_line = -1
for i, line in enumerate(lines):
    if "async def search(" in line:
        start_line = i
        break

if start_line == -1:
    print("Could not find search function")
    sys.exit(1)

# Find the end of the search function (case _: block)
end_line = -1
in_search = False
brace_count = 0
for i in range(start_line, len(lines)):
    if "case _:" in lines[i]:
        # Skip until the end of the case _: block
        for j in range(i + 1, len(lines)):
            if lines[j].strip() == "" and (j + 1 < len(lines) and (lines[j+1].startswith("#") or lines[j+1].startswith("@") or lines[j+1].startswith("async def") or lines[j+1].startswith("def"))):
                 end_line = j
                 break
            if j == len(lines) - 1:
                end_line = j
                break
        if end_line != -1:
            break

if end_line == -1:
    print("Could not find end of search function")
    sys.exit(1)

new_search_func = """@mcp.tool(
    annotations=ToolAnnotations(
        readOnlyHint=True,
        openWorldHint=True,
        idempotentHint=True,
    ),
)
@_wrap_tool("search")
async def search(  # noqa: PLR0913
    action: str,
    query: str | None = None,
    library: str | None = None,
    version: str | None = None,
    language: str | None = None,
    categories: str = "general",
    max_results: int = 10,
    limit: int = 10,
    time_range: str | None = None,
    include_domains: list[str] | None = None,
    exclude_domains: list[str] | None = None,
    expand: bool = False,
    enrich: bool = False,
) -> str:
    \"\"\"Find information across web, academic sources, or library docs. Returns search result listings (titles, URLs, snippets) -- NOT full page content. To read full content from a URL, use the `extract` tool instead.

    Actions:
    - search: Web search via SearXNG. Example: search(action="search", query="python async patterns")
    - research: Academic/scientific search (Google Scholar, arXiv, PubMed). Example: search(action="research", query="transformer attention mechanism")
    - docs: Search library documentation with auto-indexing. Example: search(action="docs", query="how to create routes", library="fastapi")
    - similar: Find pages similar to a URL (pass URL as query). Example: search(action="similar", query="https://example.com/article")

    Key parameters:
    - query (required for all actions): Search terms or URL (for similar)
    - library (required for docs): Library name, e.g. "react", "fastapi"
    - language: Programming language for disambiguation in docs, e.g. "python", "java"
    - expand: Enable LLM query expansion for broader coverage (default: false)
    - enrich: Fetch actual page content for richer snippets (default: false, adds latency)
    - max_results: Number of results (default: 10)
    - time_range: Recency filter -- day, week, month, year
    - include_domains / exclude_domains: Domain filters

    Use `help` tool with tool_name="search" for full parameter documentation.
    \"\"\"
    blocked = _require_credentials()
    if blocked:
        return blocked

    match action:
        case "search":
            if not query:
                return 'Error: query is required for search action. Example: search(action="search", query="python async patterns")'
            return await _do_web_search(
                query=query,
                categories=categories,
                max_results=max_results,
                time_range=time_range,
                language=language,
                include_domains=include_domains,
                exclude_domains=exclude_domains,
                expand=expand,
                enrich=enrich,
            )

        case "research":
            if not query:
                return 'Error: query is required for research action. Example: search(action="research", query="transformer attention mechanism")'
            return await _do_research_with_cache(
                query=query,
                max_results=max_results,
                time_range=time_range,
                language=language,
                include_domains=include_domains,
                exclude_domains=exclude_domains,
            )

        case "docs":
            if not library:
                return 'Error: library is required for docs action. Example: search(action="docs", query="routing", library="fastapi")'
            if not query:
                return 'Error: query is required for docs action. Example: search(action="docs", query="how to create routes", library="fastapi")'
            return await _with_timeout(
                _do_docs_search(
                    library=library,
                    query=query,
                    language=language,
                    version=version,
                    limit=limit,
                ),
                "docs",
            )

        case "similar":
            if not query:
                return 'Error: query (URL) is required for similar action. Example: search(action="similar", query="https://example.com/article")'
            if not query.startswith(("http://", "https://")):
                return 'Error: query must be a full URL starting with http:// or https://. Example: search(action="similar", query="https://example.com/article"). If you want to search by keywords instead, use action="search".'
            return await _do_similar_search(query, max_results=max_results)

        case _:
            import difflib

            valid_actions = ["docs", "research", "search", "similar"]
            closest = difflib.get_close_matches(action, valid_actions, n=1)
            suggestion = f" Did you mean '{closest[0]}'?" if closest else ""
            return (
                f"Error: Unknown action '{action}'.{suggestion} "
                "Valid actions: search (web search), research (academic), docs (library documentation), similar (find related pages). "
                "If you want to read content from a URL, use the `extract` tool instead."
            )
"""

# Also need to update _do_research to include caching or create a wrapper
# Let's create a wrapper for research caching to keep search clean
new_research_wrapper = """
async def _do_research_with_cache(
    query: str,
    max_results: int = 10,
    time_range: str | None = None,
    language: str | None = None,
    include_domains: list[str] | None = None,
    exclude_domains: list[str] | None = None,
) -> str:
    \"\"\"Perform academic research with caching.\"\"\"
    cache_params = {
        "query": query,
        "max_results": max_results,
        "time_range": time_range,
        "language": language,
        "include_domains": include_domains,
        "exclude_domains": exclude_domains,
    }
    if _web_cache:
        cached = await asyncio.to_thread(_web_cache.get, "research", cache_params)
        if cached:
            return cached
    result = await _with_timeout(
        _do_research(
            query=query,
            max_results=max_results,
            time_range=time_range,
            language=language,
            include_domains=include_domains,
            exclude_domains=exclude_domains,
        ),
        "research",
    )
    if _web_cache and not result.startswith("Error"):
        await asyncio.to_thread(_web_cache.set, "research", cache_params, result)
    return _format_json_result(result)
"""

# Find the line before @mcp.tool of search
search_start_index = start_line
while search_start_index > 0 and "@mcp.tool" not in lines[search_start_index]:
    search_start_index -= 1

final_lines = lines[:search_start_index] + [new_search_func + "\n"] + lines[end_line+1:]

# Add the research wrapper before _do_research
for i, line in enumerate(final_lines):
    if "async def _do_research(" in line:
        final_lines.insert(i, new_research_wrapper + "\n")
        break

with open(file_path, "w") as f:
    f.writelines(final_lines)

print(f"Successfully refactored search function and added helpers. Replaced lines {search_start_index} to {end_line}")
