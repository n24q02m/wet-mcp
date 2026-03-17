# Pre-Phase + Phase 1 (v2.14.0) Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Clean up 83 open PRs, fix security alerts, then ship v2.14.0 with search reranking, search filters, SearXNG tuning, URL dedup improvements, and local file conversion.

**Architecture:** Pre-Phase is batch merge/close of bot PRs in 5 priority batches. Phase 1 adds reranking to web search (reusing existing `_rerank_results()`), new params to `searxng.py`, SearXNG engine weights, URL normalization, and a `convert` action for local files via markitdown. New search strategies go into `sources/search_strategies.py` to prevent server.py bloat.

**Tech Stack:** Python 3.13, FastMCP, SQLite+FTS5+sqlite-vec, LiteLLM, Crawl4AI, markitdown, SearXNG, qwen3-embed

**Spec:** `docs/superpowers/specs/2026-03-17-wet-mcp-v2.14-v2.16-design.md`

---

## File Map

| File | Action | Responsibility |
|------|--------|---------------|
| `src/wet_mcp/sources/searxng.py` | Modify | Add `time_range`, `language`, `include_domains`, `exclude_domains` params; URL normalization; domain cap |
| `src/wet_mcp/server.py` | Modify | Wire new search params, add reranking to search action, add `convert` case to extract, add `paths` param |
| `src/wet_mcp/security.py` | Modify | Add `is_safe_local_path()` |
| `src/wet_mcp/sources/crawler.py` | Modify | Add `convert_local_files()`, expand `_DOCUMENT_EXTENSIONS` |
| `src/wet_mcp/config.py` | Modify | Add `convert_max_file_size`, `convert_allowed_dirs` settings |
| `src/wet_mcp/searxng_settings.yml` | Modify | Engine weights, `default_lang: auto` |
| `pyproject.toml` | Modify | Add `markitdown[xlsx]` extra |
| `tests/test_searxng.py` | Modify | Tests for new search params, URL normalization, domain cap |
| `tests/test_security.py` | Modify | Tests for `is_safe_local_path()` |
| `tests/test_server.py` | Modify | Tests for search reranking, convert action |
| `tests/test_crawler.py` | Modify | Tests for `convert_local_files()` |
| Help docs (`src/wet_mcp/docs/`) | Modify | Document new actions and params |

---

## Pre-Phase: PR Cleanup

### Task 0: PR Triage (Batch Operations)

This task is NOT TDD -- it's git operations to clean up 83 open PRs.

**Files:** None (git operations only)

- [ ] **Step 0.1: Close 33 duplicate/problematic PRs**

Close with comment explaining why (duplicate, bug, or no value):

```bash
cd /home/n24q02m/projects/wet-mcp

# Security duplicates
for pr in 397 407 430 415 388 410; do
  gh pr close $pr --comment "Closing: duplicate or superseded. See spec docs/superpowers/specs/2026-03-17-wet-mcp-v2.14-v2.16-design.md for triage details."
done

# Performance duplicates
for pr in 462 451 421 413 383 384 411 398 418 404; do
  gh pr close $pr --comment "Closing: duplicate — better implementation selected from same group."
done

# Code health duplicates/issues
for pr in 446 409 396 460 427 442 406 459; do
  gh pr close $pr --comment "Closing: duplicate or has issues (see spec for details)."
done

# Testing duplicates
for pr in 419 401 417 403 408 425 394 400; do
  gh pr close $pr --comment "Closing: duplicate — better test PR selected from same group."
done
```

- [ ] **Step 0.2: Merge Batch 1 -- Security**

```bash
gh pr merge 423 --squash --auto
```

Wait for CI to pass.

- [ ] **Step 0.3: Merge Batch 2 -- Dependencies (CI-green first)**

```bash
# These have CI green
gh pr merge 379 --squash --auto
gh pr merge 380 --squash --auto
gh pr merge 382 --squash --auto
```

After #382 merges, rebase and merge remaining:

```bash
for pr in 342 386 461; do
  gh pr comment $pr --body "Rebasing on main after batch merge."
  # Checkout, rebase, force push, then merge
done
```

- [ ] **Step 0.4: Merge Batch 3 -- Performance (8 merge, 2 fix+merge)**

Merge order to minimize conflicts (different files first):

```bash
# Independent files
gh pr merge 424 --squash --auto  # docs.py (URL sorting)
gh pr merge 414 --squash --auto  # searxng_runner.py (stderr)
gh pr merge 439 --squash --auto  # crawler.py (markitdown)

# db.py (sequential)
gh pr merge 444 --squash --auto  # import_jsonl N+1
# rebase after merge
gh pr merge 447 --squash --auto  # search N+1
gh pr merge 429 --squash --auto  # export JSONL

# server.py + cache.py
gh pr merge 399 --squash --auto  # chunk_markdown
gh pr merge 457 --squash --auto  # async cache
```

For #437 and #387, fix first then merge:

```bash
# PR #437: remove .jules/bolt.md
gh pr checkout 437
git rm .jules/bolt.md 2>/dev/null; git commit -m "fix: remove .jules/bolt.md"
git push
gh pr merge 437 --squash --auto

# PR #387: remove lru_cache
gh pr checkout 387
# Edit db.py to remove @lru_cache decorator from _chunk_quality_score
git add . && git commit -m "fix: remove lru_cache from _chunk_quality_score (memory risk)"
git push
gh pr merge 387 --squash --auto
```

- [ ] **Step 0.5: Merge Batch 4 -- Code Health (17 PRs)**

Independent PRs first (different files):

```bash
for pr in 416 405 389 432 441 453 454 445 390 428 438; do
  gh pr merge $pr --squash --auto
  sleep 5  # wait for CI
done
```

Then sequential (same files):

```bash
gh pr merge 420 --squash --auto  # __main__.py warmup
gh pr merge 448 --squash --auto  # db.py create_tables
gh pr merge 440 --squash --auto  # db.py search split
gh pr merge 452 --squash --auto  # server.py config split
gh pr merge 435 --squash --auto  # server.py config DRY
gh pr merge 456 --squash --auto  # server.py background index
```

- [ ] **Step 0.6: Merge Batch 5 -- Testing (14 PRs)**

Bug fix PRs first:

```bash
gh pr merge 402 --squash --auto  # f-string bug fix
gh pr merge 426 --squash --auto  # platform detection fix
```

Then coverage PRs:

```bash
for pr in 395 392 391 412 422 458 450 443 434 433 431 393; do
  gh pr merge $pr --squash --auto
  sleep 5
done
```

- [ ] **Step 0.7: Handle code scanning alerts**

After all PRs merged, check if the 30 `py/incomplete-url-substring-sanitization` alerts in `tests/test_docs_coverage.py` are still present. If so, dismiss as test file false positives:

```bash
gh api repos/n24q02m/wet-mcp/code-scanning/alerts --jq '.[] | select(.state=="open") | .number' | while read n; do
  gh api -X PATCH repos/n24q02m/wet-mcp/code-scanning/alerts/$n -f state=dismissed -f dismissed_reason=false_positive
done
```

- [ ] **Step 0.8: Verify clean state**

```bash
gh pr list --state open  # Should only show Renovate dashboard
gh api repos/n24q02m/wet-mcp/dependabot/alerts --jq '.[] | select(.state=="open") | .number'  # Should be 0
git pull origin main
uv run pytest  # All tests pass
```

---

## Phase 1: Search Quality + Local Files (v2.14.0)

### Task 1: SearXNG Config Improvements

**Files:**
- Modify: `src/wet_mcp/searxng_settings.yml`

- [ ] **Step 1.1: Update SearXNG settings**

Change `default_lang` from `"en-US"` to `"auto"` and add engine weights:

In `src/wet_mcp/searxng_settings.yml`:

```yaml
search:
  default_lang: "auto"
```

Add `weight` to each engine:

```yaml
engines:
  - name: google
    disabled: false
    weight: 1.5
  - name: bing
    disabled: false
    weight: 1.2
  - name: duckduckgo
    disabled: false
    weight: 1.0
  - name: brave
    disabled: false
    weight: 1.3
  - name: qwant
    disabled: false
    weight: 0.6
  - name: yahoo
    disabled: false
    weight: 0.5
  - name: startpage
    disabled: false
    weight: 0.8
```

- [ ] **Step 1.2: Commit**

```bash
git add src/wet_mcp/searxng_settings.yml
git commit -m "feat: tune SearXNG engine weights and default language to auto"
```

---

### Task 2: URL Normalization + Domain Cap in searxng.py

**Files:**
- Modify: `src/wet_mcp/sources/searxng.py`
- Test: `tests/test_searxng.py`

- [ ] **Step 2.1: Write failing tests for URL normalization**

In `tests/test_searxng.py`, add:

```python
from wet_mcp.sources.searxng import _normalize_url


def test_normalize_url_strips_www():
    assert _normalize_url("https://www.example.com/page") == "https://example.com/page"


def test_normalize_url_strips_trailing_slash():
    assert _normalize_url("https://example.com/page/") == "https://example.com/page"


def test_normalize_url_strips_tracking_params():
    url = "https://example.com/page?utm_source=google&utm_medium=cpc&real=1"
    assert _normalize_url(url) == "https://example.com/page?real=1"


def test_normalize_url_strips_fbclid():
    url = "https://example.com/page?fbclid=abc123&q=test"
    assert _normalize_url(url) == "https://example.com/page?q=test"


def test_normalize_url_no_params_after_strip():
    url = "https://example.com/page?utm_source=google"
    assert _normalize_url(url) == "https://example.com/page"


def test_normalize_url_preserves_meaningful_params():
    url = "https://example.com/search?q=test&page=2"
    assert _normalize_url(url) == "https://example.com/search?q=test&page=2"
```

- [ ] **Step 2.2: Run tests to verify they fail**

```bash
uv run pytest tests/test_searxng.py::test_normalize_url_strips_www -v
```

Expected: FAIL with `ImportError: cannot import name '_normalize_url'`

- [ ] **Step 2.3: Implement `_normalize_url` in searxng.py**

At top of `src/wet_mcp/sources/searxng.py`, after imports, add:

```python
from urllib.parse import parse_qs, urlencode, urlparse

# Tracking parameters to strip from URLs during deduplication
_TRACKING_PARAMS = frozenset({
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "fbclid", "gclid", "msclkid", "yclid", "ref", "_ga", "_gl",
    "mc_cid", "mc_eid",
})

# Maximum results from a single domain to prevent domination
_MAX_PER_DOMAIN = 3


def _normalize_url(url: str) -> str:
    """Normalize URL for deduplication: strip www, trailing slash, tracking params."""
    parsed = urlparse(url)
    netloc = parsed.netloc.removeprefix("www.")
    path = parsed.path.rstrip("/")
    params = parse_qs(parsed.query)
    clean_params = {
        k: v for k, v in params.items() if k not in _TRACKING_PARAMS
    }
    query = urlencode(clean_params, doseq=True)
    return f"{parsed.scheme}://{netloc}{path}{'?' + query if query else ''}"
```

- [ ] **Step 2.4: Run normalization tests to verify they pass**

```bash
uv run pytest tests/test_searxng.py -k "normalize_url" -v
```

Expected: All 6 PASS

- [ ] **Step 2.5: Write failing tests for domain cap**

In `tests/test_searxng.py`, add:

```python
from wet_mcp.sources.searxng import _apply_domain_cap


def test_domain_cap_limits_results():
    results = [
        {"url": f"https://example.com/page{i}", "title": f"Page {i}", "snippet": "", "source": "google"}
        for i in range(5)
    ]
    capped = _apply_domain_cap(results, max_per_domain=3)
    assert len(capped) == 3


def test_domain_cap_preserves_diversity():
    results = [
        {"url": "https://a.com/1", "title": "A1", "snippet": "", "source": ""},
        {"url": "https://a.com/2", "title": "A2", "snippet": "", "source": ""},
        {"url": "https://b.com/1", "title": "B1", "snippet": "", "source": ""},
        {"url": "https://a.com/3", "title": "A3", "snippet": "", "source": ""},
        {"url": "https://a.com/4", "title": "A4", "snippet": "", "source": ""},
        {"url": "https://b.com/2", "title": "B2", "snippet": "", "source": ""},
    ]
    capped = _apply_domain_cap(results, max_per_domain=3)
    domains = [urlparse(r["url"]).netloc for r in capped]
    assert domains.count("a.com") == 3
    assert domains.count("b.com") == 2
```

- [ ] **Step 2.6: Implement `_apply_domain_cap`**

In `src/wet_mcp/sources/searxng.py`:

```python
def _apply_domain_cap(results: list[dict], max_per_domain: int = _MAX_PER_DOMAIN) -> list[dict]:
    """Limit results per domain to prevent a single site from dominating."""
    domain_counts: dict[str, int] = {}
    capped: list[dict] = []
    for r in results:
        domain = urlparse(r["url"]).netloc.removeprefix("www.")
        count = domain_counts.get(domain, 0)
        if count < max_per_domain:
            capped.append(r)
            domain_counts[domain] = count + 1
    return capped
```

- [ ] **Step 2.7: Update dedup logic in `search()` to use normalization + domain cap**

In `src/wet_mcp/sources/searxng.py`, replace the existing dedup block (lines 130-148) in the `search()` function:

```python
                # Deduplicate by normalized URL
                seen: dict[str, dict] = {}
                for item in formatted:
                    norm_url = _normalize_url(item["url"])
                    if norm_url in seen:
                        existing = seen[norm_url]
                        if item["source"] and item["source"] not in existing["source"]:
                            existing["source"] += f", {item['source']}"
                        if len(item.get("snippet", "")) > len(
                            existing.get("snippet", "")
                        ):
                            existing["snippet"] = item["snippet"]
                            existing["title"] = item["title"] or existing["title"]
                    else:
                        seen[norm_url] = item

                deduped = _apply_domain_cap(list(seen.values()))[:max_results]
```

- [ ] **Step 2.8: Run all searxng tests**

```bash
uv run pytest tests/test_searxng.py -v
```

Expected: All PASS

- [ ] **Step 2.9: Commit**

```bash
git add src/wet_mcp/sources/searxng.py tests/test_searxng.py
git commit -m "feat: add URL normalization and per-domain result cap to search"
```

---

### Task 3: Search Filters (time_range, language, domains)

**Files:**
- Modify: `src/wet_mcp/sources/searxng.py`
- Modify: `src/wet_mcp/server.py`
- Test: `tests/test_searxng.py`

- [ ] **Step 3.1: Write failing tests for search filters**

In `tests/test_searxng.py`:

```python
def test_search_builds_domain_include_query():
    """Verify include_domains adds site: operators to query."""
    from wet_mcp.sources.searxng import _build_filtered_query
    result = _build_filtered_query("test query", include_domains=["github.com", "stackoverflow.com"])
    assert "site:github.com" in result
    assert "site:stackoverflow.com" in result
    assert "test query" in result


def test_search_builds_domain_exclude_query():
    """Verify exclude_domains adds -site: operators to query."""
    from wet_mcp.sources.searxng import _build_filtered_query
    result = _build_filtered_query("test query", exclude_domains=["pinterest.com"])
    assert "-site:pinterest.com" in result
    assert "test query" in result


def test_search_builds_combined_filter_query():
    from wet_mcp.sources.searxng import _build_filtered_query
    result = _build_filtered_query(
        "python tutorial",
        include_domains=["docs.python.org"],
        exclude_domains=["w3schools.com"],
    )
    assert "site:docs.python.org" in result
    assert "-site:w3schools.com" in result
    assert "python tutorial" in result


def test_search_no_filters_returns_original():
    from wet_mcp.sources.searxng import _build_filtered_query
    assert _build_filtered_query("test") == "test"
```

- [ ] **Step 3.2: Run tests to verify they fail**

```bash
uv run pytest tests/test_searxng.py::test_search_builds_domain_include_query -v
```

Expected: FAIL with `ImportError`

- [ ] **Step 3.3: Implement `_build_filtered_query`**

In `src/wet_mcp/sources/searxng.py`:

```python
def _build_filtered_query(
    query: str,
    include_domains: list[str] | None = None,
    exclude_domains: list[str] | None = None,
) -> str:
    """Build query string with domain include/exclude filters."""
    parts = [query]
    if include_domains:
        site_filter = " OR ".join(f"site:{d}" for d in include_domains[:5])
        parts = [f"({site_filter}) {query}"]
    if exclude_domains:
        for domain in exclude_domains[:10]:
            parts.append(f"-site:{domain}")
    return " ".join(parts)
```

- [ ] **Step 3.4: Run filter tests**

```bash
uv run pytest tests/test_searxng.py -k "build_filtered" -v
```

Expected: All 4 PASS

- [ ] **Step 3.5: Add filter params to `search()` function**

Update `search()` signature in `src/wet_mcp/sources/searxng.py`:

```python
async def search(
    searxng_url: str,
    query: str,
    categories: str = "general",
    max_results: int = 10,
    time_range: str | None = None,
    language: str | None = None,
    include_domains: list[str] | None = None,
    exclude_domains: list[str] | None = None,
) -> str:
```

Inside `search()`, before building `params`:

```python
    effective_query = _build_filtered_query(query, include_domains, exclude_domains)
```

Replace `"q": query` with `"q": effective_query` in params dict.

Add time_range and language to params:

```python
    if time_range and time_range in ("day", "week", "month", "year"):
        params["time_range"] = time_range
    if language:
        params["language"] = language
```

- [ ] **Step 3.6: Wire new params in server.py search action**

In `src/wet_mcp/server.py`, update `search()` tool signature to add:

```python
    time_range: str | None = None,
    include_domains: list[str] | None = None,
    exclude_domains: list[str] | None = None,
```

In the `case "search":` block, update `cache_params` to include new params:

```python
            cache_params = {
                "query": query,
                "categories": categories,
                "max_results": max_results,
                "time_range": time_range,
                "language": language,
                "include_domains": include_domains,
                "exclude_domains": exclude_domains,
            }
```

Update the `searxng_search()` call to pass new params:

```python
            result = await _with_timeout(
                searxng_search(
                    searxng_url=searxng_url,
                    query=query,
                    categories=categories,
                    max_results=max_results,
                    time_range=time_range,
                    language=language if action == "search" else None,
                    include_domains=include_domains,
                    exclude_domains=exclude_domains,
                ),
                "search",
            )
```

For `action="docs"`, `language` continues to be passed to `_do_docs_search` (existing behavior).

For `action="research"`, update `cache_params` and pass filters to `_do_research()`:

```python
        case "research":
            if not query:
                return "Error: query is required for research action"
            cache_params = {
                "query": query,
                "max_results": max_results,
                "time_range": time_range,
                "language": language,
                "include_domains": include_domains,
                "exclude_domains": exclude_domains,
            }
            # ... existing cache check ...
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
```

This requires updating `_do_research()` signature and its internal `searxng_search()` calls to forward these params.

**Note:** `sources/search_strategies.py` extraction is deferred to Phase 2 plan when query expansion, find similar, and snippet enrichment are added. Phase 1 only adds reranking (~15 lines) to server.py which doesn't justify a new module yet.

- [ ] **Step 3.7: Run all tests**

```bash
uv run pytest tests/test_searxng.py tests/test_server.py -v
```

Expected: All PASS

- [ ] **Step 3.8: Commit**

```bash
git add src/wet_mcp/sources/searxng.py src/wet_mcp/server.py tests/test_searxng.py
git commit -m "feat: add search filters (time_range, language, include/exclude domains)"
```

---

### Task 4: Rerank Web Search Results

**Files:**
- Modify: `src/wet_mcp/server.py`
- Test: `tests/test_server.py`

- [ ] **Step 4.1: Write failing test for search reranking**

In `tests/test_server.py`:

```python
from unittest.mock import AsyncMock, patch


async def test_search_reranks_results(mock_searxng):
    """Verify search action applies reranking when reranker is available."""
    from wet_mcp.server import search

    mock_results = {
        "results": [
            {"url": f"https://example.com/{i}", "title": f"Result {i}", "snippet": f"Content {i}", "source": "google"}
            for i in range(6)
        ],
        "total": 6,
        "query": "test",
    }

    with patch("wet_mcp.server.ensure_searxng", new_callable=AsyncMock, return_value="http://localhost:41592"), \
         patch("wet_mcp.server.searxng_search", new_callable=AsyncMock, return_value=json.dumps(mock_results)), \
         patch("wet_mcp.server._rerank_results", new_callable=AsyncMock) as mock_rerank, \
         patch("wet_mcp.server._web_cache", None):

        # Mock reranker returns top 3 with scores
        mock_rerank.return_value = [
            {"url": "https://example.com/2", "title": "Result 2", "snippet": "Content 2", "source": "google", "score": 0.9},
            {"url": "https://example.com/0", "title": "Result 0", "snippet": "Content 0", "source": "google", "score": 0.7},
            {"url": "https://example.com/4", "title": "Result 4", "snippet": "Content 4", "source": "google", "score": 0.5},
        ]

        result = await search(action="search", query="test", max_results=3)
        data = json.loads(result)

        assert mock_rerank.called
        assert data["total"] <= 3
```

- [ ] **Step 4.2: Run test to verify it fails**

```bash
uv run pytest tests/test_server.py::test_search_reranks_results -v
```

Expected: FAIL (reranking not yet wired)

- [ ] **Step 4.3: Add reranking to search action in server.py**

In `src/wet_mcp/server.py`, inside `case "search":`, after the `searxng_search()` call and before caching:

```python
            # Rerank by semantic relevance (same as research/docs)
            if not result.startswith("Error"):
                try:
                    data = json.loads(result)
                    results_list = data.get("results", [])
                    if results_list:
                        # Map snippet -> content for reranker (fallback to title)
                        for r in results_list:
                            if "content" not in r:
                                r["content"] = r.get("snippet", r.get("title", ""))
                        reranked = await _rerank_results(
                            query, results_list, top_n=max_results
                        )
                        if reranked:
                            data["results"] = [
                                r for r in reranked if r.get("score", 1.0) > 0.2
                            ]
                            data["total"] = len(data["results"])
                            result = json.dumps(data, ensure_ascii=False, indent=2)
                except Exception as e:
                    logger.debug(f"Search reranking failed, using original: {e}")
```

Also update the `searxng_search()` call to fetch more candidates:

```python
                    max_results=max_results * _RERANK_CANDIDATE_MULTIPLIER,
```

- [ ] **Step 4.4: Run test to verify it passes**

```bash
uv run pytest tests/test_server.py::test_search_reranks_results -v
```

Expected: PASS

- [ ] **Step 4.5: Run all tests**

```bash
uv run pytest -v
```

Expected: All PASS

- [ ] **Step 4.6: Commit**

```bash
git add src/wet_mcp/server.py tests/test_server.py
git commit -m "feat: add semantic reranking to web search results"
```

---

### Task 5: Local File Path Security

**Files:**
- Modify: `src/wet_mcp/security.py`
- Test: `tests/test_security.py`

- [ ] **Step 5.1: Write failing tests**

In `tests/test_security.py`:

```python
from pathlib import Path
from wet_mcp.security import is_safe_local_path


def test_safe_local_path_valid_file(tmp_path):
    f = tmp_path / "test.pdf"
    f.write_text("hello")
    result = is_safe_local_path(str(f))
    assert result == f.resolve()


def test_safe_local_path_rejects_nonexistent():
    assert is_safe_local_path("/nonexistent/file.pdf") is None


def test_safe_local_path_rejects_directory(tmp_path):
    assert is_safe_local_path(str(tmp_path)) is None


def test_safe_local_path_rejects_dotdot(tmp_path):
    f = tmp_path / "test.txt"
    f.write_text("hello")
    # Path with .. as a component is rejected
    evil_path = str(tmp_path / "subdir" / ".." / "test.txt")
    assert is_safe_local_path(evil_path) is None


def test_safe_local_path_allows_dots_in_filename(tmp_path):
    """Filenames like 'report..v2.pdf' should NOT be rejected."""
    f = tmp_path / "report..v2.txt"
    f.write_text("hello")
    assert is_safe_local_path(str(f)) is not None


def test_safe_local_path_rejects_too_large(tmp_path):
    f = tmp_path / "big.pdf"
    f.write_bytes(b"x" * 100)
    assert is_safe_local_path(str(f), max_size=50) is None


def test_safe_local_path_allowed_dirs(tmp_path):
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    f = allowed / "test.txt"
    f.write_text("hello")
    assert is_safe_local_path(str(f), allowed_dirs=[allowed]) is not None


def test_safe_local_path_rejects_outside_allowed_dirs(tmp_path):
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    f = outside / "test.txt"
    f.write_text("hello")
    assert is_safe_local_path(str(f), allowed_dirs=[allowed]) is None


def test_safe_local_path_symlink_escape(tmp_path):
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    secret = tmp_path / "secret.txt"
    secret.write_text("sensitive")
    link = allowed / "link.txt"
    link.symlink_to(secret)
    assert is_safe_local_path(str(link), allowed_dirs=[allowed]) is None
```

- [ ] **Step 5.2: Run to verify failure**

```bash
uv run pytest tests/test_security.py::test_safe_local_path_valid_file -v
```

Expected: FAIL with `ImportError`

- [ ] **Step 5.3: Implement `is_safe_local_path`**

In `src/wet_mcp/security.py`, add:

```python
_DEFAULT_MAX_FILE_SIZE = 100 * 1024 * 1024  # 100MB


def is_safe_local_path(
    path_str: str,
    allowed_dirs: list[Path] | None = None,
    max_size: int = _DEFAULT_MAX_FILE_SIZE,
) -> Path | None:
    """Validate a local file path for safe access.

    Returns resolved Path if safe, None if unsafe.

    Check order (defense-in-depth):
    1. Reject paths containing '..'
    2. Resolve symlinks and canonicalize
    3. Verify it's a regular file
    4. Check against allowed directories
    5. Check file size
    """
    # 1. Reject traversal patterns before resolution (check path components, not substring)
    from pathlib import PurePosixPath
    if ".." in PurePosixPath(path_str).parts:
        logger.warning(f"Blocked path with '..': {path_str}")
        return None

    # 2. Resolve to canonical path
    try:
        p = Path(path_str).resolve(strict=True)
    except (OSError, ValueError):
        return None

    # 3. Must be a regular file
    if not p.is_file():
        return None

    # 4. Check against allowed directories
    if allowed_dirs:
        if not any(p.is_relative_to(d.resolve()) for d in allowed_dirs):
            logger.warning(f"Blocked path outside allowed dirs: {p}")
            return None

    # 5. Check file size
    try:
        if p.stat().st_size > max_size:
            logger.warning(f"Blocked oversized file: {p} ({p.stat().st_size} bytes)")
            return None
    except OSError:
        return None

    return p
```

- [ ] **Step 5.4: Run security tests**

```bash
uv run pytest tests/test_security.py -k "safe_local_path" -v
```

Expected: All 8 PASS

- [ ] **Step 5.5: Commit**

```bash
git add src/wet_mcp/security.py tests/test_security.py
git commit -m "feat: add is_safe_local_path for local file validation"
```

---

### Task 6: Local File Convert Action

**Files:**
- Modify: `src/wet_mcp/config.py`
- Modify: `src/wet_mcp/sources/crawler.py`
- Modify: `src/wet_mcp/server.py`
- Modify: `pyproject.toml`
- Test: `tests/test_crawler.py`
- Test: `tests/test_server.py`

- [ ] **Step 6.1: Add config settings**

In `src/wet_mcp/config.py`, add to `Settings` class:

```python
    # Local file conversion
    convert_max_file_size: int = 104857600  # 100MB
    convert_allowed_dirs: str = ""  # comma-separated absolute paths, empty = allow all
```

- [ ] **Step 6.2: Update pyproject.toml**

Change markitdown dependency:

```toml
"markitdown[pdf,docx,pptx,xlsx]>=0.1.0",
```

- [ ] **Step 6.3: Write failing tests for convert_local_files**

In `tests/test_crawler.py`:

```python
import json
from wet_mcp.sources.crawler import convert_local_files


async def test_convert_local_files_txt(tmp_path):
    f = tmp_path / "test.txt"
    f.write_text("Hello, world!")
    result = await convert_local_files([str(f)])
    data = json.loads(result)
    assert len(data) == 1
    assert "Hello, world!" in data[0]["content"]
    assert data[0]["path"] == str(f)


async def test_convert_local_files_nonexistent():
    result = await convert_local_files(["/nonexistent/file.pdf"])
    data = json.loads(result)
    assert len(data) == 1
    assert "error" in data[0]


async def test_convert_local_files_csv(tmp_path):
    f = tmp_path / "data.csv"
    f.write_text("name,age\nAlice,30\nBob,25")
    result = await convert_local_files([str(f)])
    data = json.loads(result)
    assert len(data) == 1
    assert "Alice" in data[0]["content"]


async def test_convert_local_files_max_files():
    """Reject more than 10 files."""
    paths = [f"/tmp/file{i}.txt" for i in range(11)]
    result = await convert_local_files(paths)
    assert "Error" in result
```

- [ ] **Step 6.4: Run tests to verify failure**

```bash
uv run pytest tests/test_crawler.py::test_convert_local_files_txt -v
```

Expected: FAIL with `ImportError`

- [ ] **Step 6.5: Implement `convert_local_files`**

In `src/wet_mcp/sources/crawler.py`, add after imports:

```python
from wet_mcp.security import is_safe_local_path

_MAX_CONVERT_FILES = 10

# Expand document extensions for local file conversion
_LOCAL_CONVERT_EXTENSIONS = _DOCUMENT_EXTENSIONS | {
    ".csv", ".json", ".xml", ".html", ".htm", ".epub",
    ".txt", ".md", ".rst", ".log",
    ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tiff",
}
```

Then add the function:

```python
async def convert_local_files(paths: list[str]) -> str:
    """Convert local files to Markdown via markitdown.

    Args:
        paths: List of absolute file paths (max 10).

    Returns:
        JSON array of {path, content, title} or {path, error}.
    """
    if len(paths) > _MAX_CONVERT_FILES:
        return f"Error: Maximum {_MAX_CONVERT_FILES} files per call (got {len(paths)})"

    from wet_mcp.config import settings

    allowed_dirs = None
    if settings.convert_allowed_dirs:
        from pathlib import Path
        allowed_dirs = [Path(d.strip()) for d in settings.convert_allowed_dirs.split(",") if d.strip()]

    results = []
    for path_str in paths:
        safe_path = is_safe_local_path(
            path_str,
            allowed_dirs=allowed_dirs,
            max_size=settings.convert_max_file_size,
        )
        if safe_path is None:
            results.append({"path": path_str, "error": f"Path rejected: {path_str}"})
            continue

        try:
            content = await asyncio.to_thread(_convert_file, safe_path)
            results.append({
                "path": str(safe_path),
                "content": content,
                "title": safe_path.name,
            })
        except Exception as e:
            results.append({"path": path_str, "error": str(e)})

    return json.dumps(results, ensure_ascii=False, indent=2)


def _convert_file(path: "Path") -> str:
    """Synchronous file conversion via markitdown."""
    from markitdown import MarkItDown

    md = MarkItDown()
    result = md.convert(str(path))
    return result.text_content
```

- [ ] **Step 6.6: Run tests**

```bash
uv run pytest tests/test_crawler.py -k "convert_local" -v
```

Expected: All 4 PASS

- [ ] **Step 6.7: Wire convert action in server.py**

In `src/wet_mcp/server.py`, add `paths` param to `extract()` signature:

```python
async def extract(
    action: str,
    urls: list[str] | None = None,
    paths: list[str] | None = None,  # NEW: for convert action
    depth: int = 2,
    max_pages: int = 20,
    format: str = "markdown",
    stealth: bool = False,
) -> str:
```

Add new case in the `match action:` block:

```python
        case "convert":
            if not paths:
                return "Error: paths is required for convert action"
            from wet_mcp.sources.crawler import convert_local_files
            return await _with_timeout(
                convert_local_files(paths=paths),
                "convert",
            )
```

- [ ] **Step 6.8: Write server.py integration test for convert action**

In `tests/test_server.py`:

```python
async def test_extract_convert_delegates_to_convert_local_files(tmp_path):
    """Verify extract(action='convert') delegates to convert_local_files."""
    from wet_mcp.server import extract

    f = tmp_path / "test.txt"
    f.write_text("Hello from convert test")

    with patch("wet_mcp.server._with_timeout", new_callable=AsyncMock) as mock_timeout:
        mock_timeout.return_value = json.dumps([{"path": str(f), "content": "Hello from convert test", "title": "test.txt"}])
        result = await extract(action="convert", paths=[str(f)])
        data = json.loads(result)
        assert len(data) == 1
        assert data[0]["title"] == "test.txt"


async def test_extract_convert_requires_paths():
    """Verify extract(action='convert') returns error without paths."""
    from wet_mcp.server import extract
    result = await extract(action="convert")
    assert "Error" in result
    assert "paths" in result
```

- [ ] **Step 6.9: Run full test suite**

```bash
uv run pytest -v
```

Expected: All PASS

- [ ] **Step 6.9: Commit**

```bash
git add src/wet_mcp/config.py src/wet_mcp/sources/crawler.py src/wet_mcp/server.py pyproject.toml tests/test_crawler.py
git commit -m "feat: add local file convert action with security validation"
```

---

### Task 7: Update Help Docs + Final Verification

**Files:**
- Modify: `src/wet_mcp/docs/search.md` (or wherever help docs live)
- Modify: `src/wet_mcp/docs/extract.md`

- [ ] **Step 7.1: Check help docs location**

```bash
ls src/wet_mcp/docs/ 2>/dev/null || grep -r "help_text\|tool_docs" src/wet_mcp/ --include="*.py" -l
```

- [ ] **Step 7.2: Update search tool documentation**

Add to search help docs:

```markdown
### Filters (search and research actions)
- `time_range`: Filter by time — "day", "week", "month", "year"
- `language`: Search language code — "en", "vi", "ja" (for search/research: SearXNG language; for docs: library language disambiguation)
- `include_domains`: Only include results from these domains (max 5) — ["github.com", "stackoverflow.com"]
- `exclude_domains`: Exclude results from these domains (max 10) — ["pinterest.com"]
```

- [ ] **Step 7.3: Update extract tool documentation**

Add to extract help docs:

```markdown
### convert action
Convert local files to Markdown. Supports: PDF, DOCX, PPTX, XLSX, CSV, JSON, XML, HTML, EPUB, TXT, images (EXIF metadata).

Parameters:
- `paths` (required): List of absolute file paths (max 10)

Example: `extract(action="convert", paths=["/home/user/report.pdf", "/home/user/data.xlsx"])`

Security: Paths are validated against traversal attacks, symlink escapes, and optional directory allowlist (CONVERT_ALLOWED_DIRS).
```

- [ ] **Step 7.4: Run full lint + test suite**

```bash
uv run ruff check . && uv run ruff format --check . && uv run ty check && uv run pytest -v
```

Expected: All pass

- [ ] **Step 7.5: Commit docs**

```bash
git add src/wet_mcp/docs/
git commit -m "docs: update help docs for search filters and convert action"
```

- [ ] **Step 7.6: Final integration test (manual)**

```bash
uv run wet-mcp  # Start server, test tools manually via MCP client
```

Verify:
1. `search(action="search", query="python async", time_range="week")` returns time-filtered results
2. `search(action="search", query="react hooks", include_domains=["react.dev"])` returns only react.dev results
3. `extract(action="convert", paths=["/path/to/local/file.pdf"])` returns markdown content
4. Search results are reranked (check logs for "Reranking" messages)

---

## Summary

| Task | Description | Key Files |
|------|-------------|-----------|
| 0 | PR Triage (close 33, merge 48) | git operations |
| 1 | SearXNG config (weights, auto lang) | `searxng_settings.yml` |
| 2 | URL normalization + domain cap | `sources/searxng.py` |
| 3 | Search filters (time, lang, domains) | `sources/searxng.py`, `server.py` |
| 4 | Rerank web search results | `server.py` |
| 5 | Local file path security | `security.py` |
| 6 | Local file convert action | `crawler.py`, `server.py`, `config.py` |
| 7 | Help docs + final verification | docs, integration test |
