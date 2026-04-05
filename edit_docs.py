import re

with open('src/wet_mcp/sources/docs.py', 'r') as f:
    content = f.read()

# 1. Add _score_url and _sort_by_query at module level
new_functions = """
def _score_url(url: str, query_words: frozenset[str], title: str = "") -> int:
    \"\"\"Score a URL based on query term overlap in path or title.\"\"\"
    score = 0
    path = urlparse(url).path.lower()
    path_words = set(
        path.replace("-", " ")
        .replace("_", " ")
        .replace("/", " ")
        .replace(".", " ")
        .split()
    )
    score += len(query_words & path_words)

    if title:
        title_words = set(title.lower().split())
        score += len(query_words & title_words)

    return score


def _sort_by_query(urls: list[str], query: str) -> list[str]:
    \"\"\"Sort URLs by query term overlap (highest first).\"\"\"
    if not query or not urls:
        return urls
    query_words = frozenset(query.lower().split())

    def score_url(url: str) -> int:
        return _score_url(url, query_words)

    return sorted(urls, key=score_url, reverse=True)
"""

content = content.replace(
    "# Docs fetching with Crawl4AI",
    "# Docs sorting and relevance scoring\n# ---------------------------------------------------------------------------\n" + new_functions + "\n# ---------------------------------------------------------------------------\n# Docs fetching with Crawl4AI"
)

# 2. Remove internal _sort_by_query and update calls
# First, remove the internal definition
internal_def_pattern = re.compile(
    r'    def _sort_by_query\(urls: list\[str\]\) -> list\[str\]:.*?return sorted\(urls, key=score_url, reverse=True\)',
    re.DOTALL
)
content = internal_def_pattern.sub('', content)

# Update calls to _sort_by_query(pending_urls) -> _sort_by_query(pending_urls, query)
content = content.replace(
    'pending_urls = _sort_by_query(pending_urls)',
    'pending_urls = _sort_by_query(pending_urls, query)'
)

with open('src/wet_mcp/sources/docs.py', 'w') as f:
    f.write(content)
