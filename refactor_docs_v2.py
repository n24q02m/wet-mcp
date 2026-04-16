import sys

def refactor():
    with open('src/wet_mcp/sources/docs.py', 'r') as f:
        lines = f.readlines()

    insert_pos = -1
    for i, line in enumerate(lines):
        if 'async def fetch_docs_pages' in line:
            for j in range(i, 0, -1):
                if '@dataclass' in lines[j]:
                    insert_pos = j
                    break
            break

    if insert_pos == -1:
        print("Could not find insertion point")
        sys.exit(1)

    helper_lines = [
        "def _filter_doc_url(url: str, ctx: \"DocsCrawlContext\") -> bool:\n",
        "    \"\"\"Check if a URL should be included in the documentation crawl.\"\"\"\n",
        "    parsed = urlparse(url)\n",
        "    if parsed.netloc and parsed.netloc != ctx.docs_parsed.netloc:\n",
        "        return False\n",
        "\n",
        "    full_url = urljoin(ctx.docs_url, url)\n",
        "    if full_url in ctx.seen_urls:\n",
        "        return False\n",
        "\n",
        "    full_parsed = urlparse(full_url)\n",
        "    path_lower = full_parsed.path.lower()\n",
        "\n",
        "    # Skip generated index/module pages\n",
        "    if any(pat in path_lower for pat in _SKIP_URL_PATTERNS):\n",
        "        return False\n",
        "\n",
        "    # GitHub-specific: stay within same repo\n",
        "    if ctx.is_github:\n",
        "        path_parts = full_parsed.path.strip(\"/\").split(\"/\")\n",
        "        if path_parts and path_parts[0] in _GH_SKIP_PATHS:\n",
        "            return False\n",
        "        if \"/\".join(path_parts[:2]) != ctx.gh_path_prefix:\n",
        "            return False\n",
        "\n",
        "    # Skip translated (non-English) pages\n",
        "    if _is_i18n_url(full_parsed.path, ctx.docs_parsed.path):\n",
        "        return False\n",
        "\n",
        "    # Versioned docs: restrict to same version path prefix\n",
        "    if ctx.version_prefix and not full_parsed.path.startswith(ctx.version_prefix):\n",
        "        return False\n",
        "\n",
        "    return True\n",
        "\n",
        "\n",
        "def _sort_urls_by_query(urls: list[str], query: str) -> list[str]:\n",
        "    \"\"\"Sort URLs by query term overlap (highest first).\"\"\"\n",
        "    if not query or not urls:\n",
        "        return urls\n",
        "    query_words = frozenset(query.lower().split())\n",
        "\n",
        "    def score_url(url: str) -> int:\n",
        "        path = urlparse(url).path.lower()\n",
        "        path_words = set(\n",
        "            path.replace(\"-\", \" \")\n",
        "            .replace(\"_\", \" \")\n",
        "            .replace(\"/\", \" \")\n",
        "            .replace(\".\", \" \")\n",
        "            .split()\n",
        "        )\n",
        "        return len(query_words & path_words)\n",
        "\n",
        "    return sorted(urls, key=score_url, reverse=True)\n",
        "\n",
        "\n",
        "def _process_crawl_results(\n",
        "    results: list[dict], ctx: \"DocsCrawlContext\", discover_links: bool = True\n",
        ") -> None:\n",
        "    \"\"\"Process results from a crawl batch and update context state.\"\"\"\n",
        "    for r in results:\n",
        "        content = r.get(\"content\")\n",
        "        if not content or r.get(\"error\"):\n",
        "            continue\n",
        "\n",
        "        if _is_blocked_content(content):\n",
        "            ctx.blocked_count += 1\n",
        "            continue\n",
        "\n",
        "        ctx.pages.append(\n",
        "            {\n",
        "                \"url\": r[\"url\"],\n",
        "                \"title\": r.get(\"title\", \"\"),\n",
        "                \"content\": content,\n",
        "            }\n",
        "        )\n",
        "\n",
        "        if discover_links:\n",
        "            internal = r.get(\"links\", {}).get(\"internal\", [])\n",
        "            for link in internal:\n",
        "                href = link.get(\"href\", \"\") if isinstance(link, dict) else link\n",
        "                if not href:\n",
        "                    continue\n",
        "\n",
        "                if _filter_doc_url(href, ctx):\n",
        "                    full_url = urljoin(ctx.docs_url, href)\n",
        "                    ctx.pending_urls.append(full_url)\n",
        "                    ctx.seen_urls.add(full_url)\n",
        "\n",
        "\n"
    ]

    new_lines = lines[:insert_pos] + helper_lines + lines[insert_pos:]

    with open('src/wet_mcp/sources/docs.py', 'w') as f:
        f.writelines(new_lines)

if __name__ == "__main__":
    refactor()
