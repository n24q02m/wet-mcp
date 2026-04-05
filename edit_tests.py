import re

with open('tests/test_docs_coverage.py', 'r') as f:
    content = f.read()

# 1. Add _score_url and _sort_by_query to imports
content = content.replace(
    '    _normalize_docs_url,',
    '    _normalize_docs_url,\n    _score_url,\n    _sort_by_query,'
)

# 2. Add the test functions at the end of the file
test_code = """
# ---------------------------------------------------------------------------
# _score_url and _sort_by_query
# ---------------------------------------------------------------------------


def test_score_url_basic():
    \"\"\"Score counts overlapping words between query and URL path.\"\"\"
    query_words = frozenset(["getting", "started"])

    # Full match (2 words)
    assert _score_url("https://docs.test/getting-started", query_words) == 2

    # Partial match (1 word)
    assert _score_url("https://docs.test/getting", query_words) == 1

    # No match
    assert _score_url("https://docs.test/api-reference", query_words) == 0


def test_score_url_delimiters():
    \"\"\"Score correctly handles different path delimiters.\"\"\"
    query_words = frozenset(["api", "ref"])

    assert _score_url("https://docs.test/api_ref", query_words) == 2
    assert _score_url("https://docs.test/api/ref.html", query_words) == 2
    assert _score_url("https://docs.test/api-ref", query_words) == 2


def test_score_url_with_title():
    \"\"\"Score includes title overlap if provided.\"\"\"
    query_words = frozenset(["install"])

    # Path match
    assert _score_url("https://docs.test/install", query_words) == 1

    # Title match
    assert _score_url("https://docs.test/page1", query_words, title="Installation Guide") == 1

    # Both match
    assert _score_url("https://docs.test/install", query_words, title="Installation Guide") == 2


def test_sort_by_query_functional():
    \"\"\"_sort_by_query correctly orders a list of URLs.\"\"\"
    urls = [
        "https://docs.test/api-ref",
        "https://docs.test/getting-started",
        "https://docs.test/other",
    ]
    query = "getting started"

    sorted_urls = _sort_by_query(urls, query)

    assert sorted_urls[0] == "https://docs.test/getting-started"
    assert "https://docs.test/api-ref" in sorted_urls
    assert "https://docs.test/other" in sorted_urls


def test_sort_by_query_empty():
    \"\"\"_sort_by_query handles empty inputs gracefully.\"\"\"
    urls = ["https://docs.test/1"]

    # No query
    assert _sort_by_query(urls, "") == urls

    # No URLs
    assert _sort_by_query([], "query") == []
"""

content += test_code

with open('tests/test_docs_coverage.py', 'w') as f:
    f.write(content)
