"""Library documentation discovery and indexing.

Handles the full pipeline: discover docs URL from library name,
fetch content, chunk it, and store in DocsDB.

Discovery tiers (tried in order):
1. llms.txt / llms-full.txt — AI-friendly docs standard
2. Package registry metadata — npm, PyPI, crates.io, Go
3. SearXNG web search — fallback discovery

Content fetching:
- Reuses Crawl4AI from crawler module
- Reuses WebCache extract entries when available
"""

import asyncio
import json
import re
from urllib.parse import urljoin, urlparse

import httpx
from loguru import logger

# Bump this whenever discovery scoring or crawl logic changes.
# Libraries cached with an older version are automatically re-indexed.
DISCOVERY_VERSION = 3

# ---------------------------------------------------------------------------
# Registry discovery — find docs URL from library name
# ---------------------------------------------------------------------------


async def _discover_from_npm(name: str) -> dict | None:
    """Query npm registry for package metadata."""
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(f"https://registry.npmjs.org/{name}")
            if resp.status_code != 200:
                return None
            data = resp.json()
            return {
                "name": data.get("name", name),
                "description": data.get("description", ""),
                "homepage": data.get("homepage", ""),
                "repository": data.get("repository", {}).get("url", "")
                if isinstance(data.get("repository"), dict)
                else data.get("repository", ""),
                "registry": "npm",
            }
    except Exception as e:
        logger.debug(f"npm lookup failed for {name}: {e}")
        return None


async def _discover_from_pypi(name: str) -> dict | None:
    """Query PyPI JSON API for package metadata."""
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(f"https://pypi.org/pypi/{name}/json")
            if resp.status_code != 200:
                return None
            data = resp.json()
            info = data.get("info", {})
            project_urls = info.get("project_urls") or {}
            docs_url = (
                project_urls.get("Documentation")
                or project_urls.get("Docs")
                or project_urls.get("docs")
                or info.get("docs_url")
                or info.get("home_page")
                or ""
            )
            return {
                "name": info.get("name", name),
                "description": info.get("summary", ""),
                "homepage": docs_url or info.get("home_page", ""),
                "repository": project_urls.get("Repository", "")
                or project_urls.get("Source", ""),
                "registry": "pypi",
            }
    except Exception as e:
        logger.debug(f"PyPI lookup failed for {name}: {e}")
        return None


async def _discover_from_crates(name: str) -> dict | None:
    """Query crates.io API for package metadata."""
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"https://crates.io/api/v1/crates/{name}",
                headers={"User-Agent": "wet-mcp/1.0"},
            )
            if resp.status_code != 200:
                return None
            crate = resp.json().get("crate", {})
            return {
                "name": crate.get("name", name),
                "description": crate.get("description", ""),
                "homepage": crate.get("documentation")
                or crate.get("homepage")
                or f"https://docs.rs/{name}",
                "repository": crate.get("repository", ""),
                "registry": "crates",
            }
    except Exception as e:
        logger.debug(f"crates.io lookup failed for {name}: {e}")
        return None


async def discover_library(name: str) -> dict | None:
    """Discover library metadata from package registries.

    Queries npm, PyPI, and crates.io in parallel. Scores by:
    1. Exact name match (case-insensitive)
    2. Has valid docs/homepage URL
    3. Non-GitHub homepage (custom domain = established project)
    4. Description length (longer = more established)
    5. Dedicated docs URL pattern (readthedocs, docs.*, etc.)

    This prevents e.g. npm's obscure "fastapi" package from shadowing
    Python's FastAPI, or npm "torch" from shadowing PyTorch.
    """
    results = await asyncio.gather(
        _discover_from_npm(name),
        _discover_from_pypi(name),
        _discover_from_crates(name),
        return_exceptions=True,
    )

    # Score each result for relevance
    scored: list[tuple[int, dict]] = []
    for r in results:
        if not isinstance(r, dict):
            continue
        score = 0
        # Exact name match is the strongest signal
        if r.get("name", "").lower() == name.lower():
            score += 10
        # Has a docs/homepage URL
        homepage = r.get("homepage", "")
        if homepage:
            score += 5
            # Non-GitHub homepage = established project with custom domain
            parsed_hp = urlparse(homepage)
            if parsed_hp.netloc and "github.com" not in parsed_hp.netloc:
                score += 3
                # Library name appears in the domain → likely official site
                # e.g. fastapi.tiangolo.com, pytorch.org, react.dev
                lib_norm = name.lower().replace("-", "")
                host_norm = parsed_hp.netloc.lower().replace("-", "")
                if lib_norm in host_norm:
                    score += 3
                # Known dedicated docs platforms (not generic hosts like docs.rs)
                if any(p in parsed_hp.netloc for p in ("readthedocs", "rtfd.io")):
                    score += 2
        # Description quality (longer = more established)
        desc = r.get("description", "")
        if desc:
            desc_len = len(desc)
            if desc_len > 100:
                score += 3
            elif desc_len > 50:
                score += 2
            elif desc_len > 20:
                score += 1
        scored.append((score, r))

    # Sort by score descending, pick best
    scored.sort(key=lambda x: x[0], reverse=True)

    if scored:
        best_score, best = scored[0]
        if best.get("homepage"):
            logger.info(
                f"Discovered {name} docs: {best['homepage']} "
                f"(via {best['registry']}, score={best_score})"
            )
            return best
        # No homepage but has some data
        return best

    return None


# ---------------------------------------------------------------------------
# llms.txt discovery — try to fetch AI-friendly docs
# ---------------------------------------------------------------------------


async def try_llms_txt(base_url: str) -> str | None:
    """Try fetching llms-full.txt or llms.txt from a site.

    Returns content if found, None otherwise.
    """
    if not base_url:
        return None

    parsed = urlparse(base_url)
    origin = f"{parsed.scheme}://{parsed.netloc}"

    # Try both variants — prefer llms-full.txt (actual content)
    for filename in ("llms-full.txt", "llms.txt"):
        url = f"{origin}/{filename}"
        try:
            async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
                resp = await client.get(url)
                if resp.status_code == 200:
                    content = resp.text
                    # Validate: should be substantial text, not an error page
                    if len(content) > 200 and not content.strip().startswith(
                        "<!DOCTYPE"
                    ):
                        # llms.txt (non-full) is often just a TOC with links.
                        # Check quality: if >50% of non-empty lines are just
                        # markdown links, skip — better to crawl actual pages.
                        if filename == "llms.txt" and _is_toc_only(content):
                            logger.info(
                                f"Skipping {url}: TOC-only content, "
                                "will fall back to crawling"
                            )
                            continue
                        logger.info(f"Found {filename} at {url} ({len(content)} chars)")
                        return content
        except Exception:
            continue

    return None


def _is_toc_only(content: str) -> bool:
    """Check if content is mostly a table of contents (links only).

    Returns True if >50% of non-empty lines are markdown links or bare URLs,
    indicating the file is just a TOC rather than actual documentation.
    """
    lines = [line.strip() for line in content.splitlines() if line.strip()]
    if not lines:
        return True

    # Patterns that indicate a TOC line (not actual content)
    link_pattern = re.compile(
        r"^[-*]\s*\[.+?\]\(.+?\)\s*$"  # - [Title](url) or * [Title](url)
        r"|^\[.+?\]\(.+?\)\s*$"  # [Title](url) bare
        r"|^https?://\S+\s*$"  # bare URL
        r"|^>\s*[-*]?\s*\[.+?\]\(.+?\)"  # > - [Title](url) quoted
    )
    toc_lines = sum(1 for line in lines if link_pattern.match(line))

    # Also count heading-only lines (# Title without body)
    heading_lines = sum(1 for line in lines if line.startswith("#"))

    content_lines = len(lines) - toc_lines - heading_lines
    # If less than 50% of lines are actual content, it's a TOC
    return content_lines < len(lines) * 0.5


# ---------------------------------------------------------------------------
# Content chunking — split docs into searchable chunks
# ---------------------------------------------------------------------------

# Heading pattern for markdown
_HEADING_RE = re.compile(r"^(#{1,4})\s+(.+)$", re.MULTILINE)


def chunk_markdown(
    content: str,
    url: str = "",
    max_chunk_size: int = 1500,
    min_chunk_size: int = 100,
) -> list[dict]:
    """Split markdown content into semantic chunks by headings.

    Splits on ## and ### headings, keeping heading hierarchy.
    Chunks that are too large are further split by paragraphs.
    """
    if not content or not content.strip():
        return []

    chunks: list[dict] = []
    current_title = ""
    heading_path = ""
    current_lines: list[str] = []

    def _flush():
        nonlocal current_lines
        text = "\n".join(current_lines).strip()
        if len(text) >= min_chunk_size:
            # Split oversized chunks by double newline
            if len(text) > max_chunk_size:
                parts = text.split("\n\n")
                buffer = ""
                for part in parts:
                    if len(buffer) + len(part) + 2 > max_chunk_size and buffer:
                        chunks.append(
                            {
                                "content": buffer.strip(),
                                "title": current_title,
                                "heading_path": heading_path,
                                "url": url,
                                "chunk_index": len(chunks),
                            }
                        )
                        buffer = part
                    else:
                        buffer = f"{buffer}\n\n{part}" if buffer else part
                if buffer.strip() and len(buffer.strip()) >= min_chunk_size:
                    chunks.append(
                        {
                            "content": buffer.strip(),
                            "title": current_title,
                            "heading_path": heading_path,
                            "url": url,
                            "chunk_index": len(chunks),
                        }
                    )
            else:
                chunks.append(
                    {
                        "content": text,
                        "title": current_title,
                        "heading_path": heading_path,
                        "url": url,
                        "chunk_index": len(chunks),
                    }
                )
        current_lines = []

    h1 = ""
    h2 = ""

    for line in content.split("\n"):
        heading_match = _HEADING_RE.match(line)
        if heading_match:
            level = len(heading_match.group(1))
            heading_text = heading_match.group(2).strip()

            if level <= 2:
                _flush()
                if level == 1:
                    h1 = heading_text
                    h2 = ""
                else:
                    h2 = heading_text
                current_title = heading_text
                heading_path = f"{h1} > {h2}" if h2 else h1

            elif level <= 4:
                # Flush if current chunk is big enough
                if len("\n".join(current_lines)) > max_chunk_size // 2:
                    _flush()
                current_title = heading_text
                heading_path = " > ".join(filter(None, [h1, h2, heading_text]))

        current_lines.append(line)

    # Flush remaining
    _flush()

    return chunks


def chunk_llms_txt(content: str, base_url: str = "") -> list[dict]:
    """Chunk llms.txt / llms-full.txt content.

    llms.txt format uses markdown with clear section headers.
    """
    return chunk_markdown(content, url=base_url, max_chunk_size=2000)


# ---------------------------------------------------------------------------
# Docs fetching with Crawl4AI
# ---------------------------------------------------------------------------


async def fetch_docs_pages(
    docs_url: str,
    query: str = "",
    max_pages: int = 30,
) -> list[dict]:
    """Fetch documentation pages from a docs site.

    Strategy:
    1. Fetch the root docs page
    2. Extract internal links (likely docs pages)
    3. Filter to most relevant pages based on query
    4. Fetch remaining pages

    Returns list of {url, title, content} dicts.
    """
    from wet_mcp.sources.crawler import extract

    # Step 1: Fetch root page
    logger.info(f"Fetching docs root: {docs_url}")
    root_result_str = await extract(urls=[docs_url], format="markdown", stealth=True)
    root_results = json.loads(root_result_str)

    pages: list[dict] = []
    seen_urls: set[str] = {docs_url}

    # For GitHub URLs, restrict crawl to the same repo path
    docs_parsed = urlparse(docs_url)
    _is_github = "github.com" in docs_parsed.netloc
    # Extract /org/repo prefix for GitHub URLs
    _gh_path_prefix = "/".join(docs_parsed.path.strip("/").split("/")[:2])
    # Known non-docs GitHub paths to skip
    _gh_skip_paths = {
        "features",
        "enterprise",
        "copilot",
        "marketplace",
        "security",
        "sponsors",
        "login",
        "signup",
        "about",
        "pricing",
        "customer-stories",
        "why-github",
    }

    for r in root_results:
        if r.get("content") and not r.get("error"):
            pages.append(
                {
                    "url": r["url"],
                    "title": r.get("title", ""),
                    "content": r["content"],
                }
            )

            # Collect internal links for further crawling
            internal_links = r.get("links", {}).get("internal", [])
            link_urls = []
            for link in internal_links:
                href = link.get("href", "") if isinstance(link, dict) else link
                if href and href not in seen_urls:
                    # Only follow docs-like paths
                    parsed = urlparse(href)
                    if parsed.netloc == docs_parsed.netloc or not parsed.netloc:
                        full_url = urljoin(docs_url, href)
                        full_parsed = urlparse(full_url)

                        # GitHub-specific: stay within same repo
                        if _is_github:
                            path_parts = full_parsed.path.strip("/").split("/")
                            # Skip known non-docs paths
                            if path_parts and path_parts[0] in _gh_skip_paths:
                                continue
                            # Must be within same org/repo
                            link_prefix = "/".join(path_parts[:2])
                            if link_prefix != _gh_path_prefix:
                                continue

                        if full_url not in seen_urls:
                            link_urls.append(full_url)
                            seen_urls.add(full_url)

            # If we have a query, prioritize relevant links
            if query and link_urls:
                query_words = set(query.lower().split())
                scored = []
                for url in link_urls:
                    path_words = set(re.split(r"[-_/.]", urlparse(url).path.lower()))
                    overlap = len(query_words & path_words)
                    scored.append((url, overlap))
                scored.sort(key=lambda x: x[1], reverse=True)
                link_urls = [u for u, _ in scored]

            # Fetch additional pages (limited)
            remaining = max_pages - len(pages)
            if remaining > 0 and link_urls:
                batch_urls = link_urls[:remaining]
                logger.info(f"Fetching {len(batch_urls)} additional docs pages...")
                batch_str = await extract(
                    urls=batch_urls, format="markdown", stealth=True
                )
                batch_results = json.loads(batch_str)
                for br in batch_results:
                    if br.get("content") and not br.get("error"):
                        pages.append(
                            {
                                "url": br["url"],
                                "title": br.get("title", ""),
                                "content": br["content"],
                            }
                        )

    logger.info(f"Fetched {len(pages)} docs pages from {docs_url}")
    return pages
