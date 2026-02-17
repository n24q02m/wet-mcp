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
import os
import re
import zlib
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx
from loguru import logger

# Bump this whenever discovery scoring or crawl logic changes.
# Libraries cached with an older version are automatically re-indexed.
DISCOVERY_VERSION = 24


def _github_headers() -> dict[str, str]:
    """Return GitHub API headers, including auth token if available."""
    headers: dict[str, str] = {}
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token:
        headers["Authorization"] = f"token {token}"
    return headers


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

            # Detect deprecated packages (npm deprecate-holder, squatted names)
            is_deprecated = False
            dist_tags = data.get("dist-tags", {})
            latest_ver = dist_tags.get("latest", "")
            if latest_ver and isinstance(data.get("versions"), dict):
                ver_info = data["versions"].get(latest_ver, {})
                if ver_info.get("deprecated"):
                    is_deprecated = True

            repo_url = (
                data.get("repository", {}).get("url", "")
                if isinstance(data.get("repository"), dict)
                else (data.get("repository") or "")
            )
            # npm shorthand "owner/repo" → full GitHub URL
            if (
                repo_url
                and "/" in repo_url
                and "://" not in repo_url
                and not repo_url.startswith("git+")
            ):
                repo_url = f"https://github.com/{repo_url}"
            return {
                "name": data.get("name", name),
                "description": data.get("description", ""),
                "homepage": data.get("homepage") or "",
                "repository": repo_url,
                "registry": "npm",
                "deprecated": is_deprecated,
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
            # Case-insensitive project_urls lookup (PyPI has inconsistent casing)
            project_urls_lower = {k.lower(): v for k, v in project_urls.items() if v}
            docs_url = (
                project_urls_lower.get("documentation")
                or project_urls_lower.get("docs")
                or project_urls_lower.get("homepage")
                or info.get("docs_url")
                or info.get("home_page")
                or ""
            )
            repo_url = (
                project_urls_lower.get("repository")
                or project_urls_lower.get("source")
                or project_urls_lower.get("source code")
                or project_urls_lower.get("code")
                or ""
            )
            # Fallback: extract GitHub URL from any project_urls value
            # Many PyPI packages list GitHub under "Homepage", "Bug Tracker",
            # "Changelog", etc. without a dedicated "Repository" key.
            if not repo_url or "github.com" not in repo_url:
                for _key, url_val in project_urls_lower.items():
                    if url_val and "github.com" in url_val:
                        repo_url = url_val
                        break
            # Last resort: check top-level home_page field
            if not repo_url or "github.com" not in repo_url:
                hp = info.get("home_page") or ""
                if "github.com" in hp:
                    repo_url = hp
            return {
                "name": info.get("name", name),
                "description": info.get("summary") or "",
                "homepage": docs_url or info.get("home_page") or "",
                "repository": repo_url,
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
            docs_url = crate.get("documentation") or ""
            hp_url = crate.get("homepage") or ""
            # Filter self-referencing crates.io URLs (listing page, not docs)
            if hp_url and "crates.io" in hp_url:
                hp_url = ""
            # Prefer homepage over docs.rs auto-generated documentation
            if hp_url:
                explicit_url = hp_url
            elif docs_url and "docs.rs" not in docs_url:
                explicit_url = docs_url
            else:
                explicit_url = ""
            # Use docs.rs fallback when no custom homepage/docs URL exists
            is_fallback = not explicit_url
            final_url = explicit_url or docs_url or f"https://docs.rs/{name}"
            return {
                "name": crate.get("name", name),
                "description": crate.get("description") or "",
                "homepage": final_url,
                "repository": crate.get("repository") or "",
                "registry": "crates",
                "docs_rs_fallback": is_fallback,
                "downloads": crate.get("downloads") or 0,
            }
    except Exception as e:
        logger.debug(f"crates.io lookup failed for {name}: {e}")
        return None


async def _discover_from_go(name: str) -> dict | None:
    """Query pkg.go.dev for Go module metadata.

    Searches pkg.go.dev for the package name and returns the top result.
    Falls back to GitHub API search for Go repositories if no direct match.
    This enables discovery of Go-only libraries like gin, echo, etc.
    """
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            # For Go packages with slash (e.g. "gorilla/mux"), search by
            # org or full name; for simple names, search by name alone.
            search_name = name.split("/")[-1] if "/" in name else name
            # Try GitHub search for Go repos with this name
            resp = await client.get(
                "https://api.github.com/search/repositories",
                params={
                    "q": f"{search_name} language:go",
                    "sort": "stars",
                    "per_page": 5,
                },
                headers=_github_headers(),
            )
            if resp.status_code != 200:
                return None
            items = resp.json().get("items", [])
            if not items:
                return None

            # Find the most relevant Go repo
            name_lower = name.lower()
            for item in items:
                repo_name = item.get("name", "").lower()
                full_name = item.get("full_name", "")
                full_name_lower = full_name.lower()
                # Match by repo name OR full_name for org/repo style
                name_match = False
                if "/" in name_lower:
                    # "gorilla/mux" should match full_name "gorilla/mux"
                    name_match = full_name_lower == name_lower
                else:
                    name_match = repo_name == name_lower
                if not name_match:
                    continue
                if item.get("language", "").lower() != "go":
                    continue
                # Require minimum popularity to avoid junk/clone repos
                stars = item.get("stargazers_count", 0)
                if stars < 50:
                    continue
                homepage = item.get("homepage") or ""
                description = item.get("description") or ""
                repo_url = item.get("html_url") or ""
                # Use homepage if it's a real docs domain (not github.com itself)
                if homepage and "github.com" not in homepage.lower():
                    docs_url = homepage
                else:
                    docs_url = f"https://pkg.go.dev/github.com/{full_name}"
                return {
                    "name": name,
                    "description": description,
                    "homepage": docs_url,
                    "repository": repo_url,
                    "registry": "go",
                    "stars": stars,
                }
    except Exception as e:
        logger.debug(f"Go module lookup failed for {name}: {e}")
        return None


# ---------------------------------------------------------------------------
# Additional registry discovery functions
# ---------------------------------------------------------------------------


async def _discover_from_hex(name: str) -> dict | None:
    """Query Hex.pm API for Elixir/Erlang package metadata."""
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"https://hex.pm/api/packages/{name}",
                headers={"Accept": "application/json"},
            )
            if resp.status_code != 200:
                return None
            data = resp.json()
            meta = data.get("meta", {})
            links = meta.get("links", {})
            # Case-insensitive links lookup
            links_lower = {k.lower(): v for k, v in links.items() if v}
            docs_url = (
                data.get("docs_html_url")
                or links_lower.get("documentation")
                or links_lower.get("docs")
                or links_lower.get("homepage")
                or ""
            )
            repo_url = (
                links_lower.get("github")
                or links_lower.get("repository")
                or links_lower.get("source")
                or ""
            )
            # Fallback: hexdocs.pm is the standard Elixir docs host
            if not docs_url:
                docs_url = f"https://hexdocs.pm/{name}"
            return {
                "name": data.get("name", name),
                "description": meta.get("description") or "",
                "homepage": docs_url,
                "repository": repo_url,
                "registry": "hex",
                "downloads": data.get("downloads", {}).get("all", 0),
            }
    except Exception as e:
        logger.debug(f"Hex.pm lookup failed for {name}: {e}")
        return None


async def _discover_from_packagist(name: str) -> dict | None:
    """Query Packagist API for PHP package metadata.

    ``name`` can be either ``vendor/package`` (exact) or just ``package``
    (searches by keyword and picks the best match).
    """
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            if "/" in name:
                # Exact vendor/package lookup
                resp = await client.get(f"https://repo.packagist.org/p2/{name}.json")
                if resp.status_code != 200:
                    return None
                data = resp.json()
                packages = data.get("packages", {}).get(name, [])
                if not packages:
                    return None
                latest = packages[0]  # First entry is latest
                return {
                    "name": name,
                    "description": latest.get("description") or "",
                    "homepage": latest.get("homepage") or "",
                    "repository": latest.get("source", {})
                    .get("url", "")
                    .replace("git+", "")
                    .replace(".git", ""),
                    "registry": "packagist",
                }
            else:
                # Search by keyword
                resp = await client.get(
                    "https://packagist.org/search.json",
                    params={"q": name, "per_page": 5},
                )
                if resp.status_code != 200:
                    return None
                results = resp.json().get("results", [])
                if not results:
                    return None
                # Prefer exact name match on package part
                name_lower = name.lower()
                best = None
                for r in results:
                    pkg_name = r.get("name", "")
                    pkg_part = (
                        pkg_name.split("/")[-1].lower()
                        if "/" in pkg_name
                        else pkg_name.lower()
                    )
                    if pkg_part == name_lower:
                        best = r
                        break
                if not best:
                    best = results[0]
                repo_url = best.get("repository") or ""
                return {
                    "name": best.get("name", name),
                    "description": best.get("description") or "",
                    "homepage": best.get("url") or "",
                    "repository": repo_url.replace(".git", ""),
                    "registry": "packagist",
                    "downloads": best.get("downloads", 0),
                }
    except Exception as e:
        logger.debug(f"Packagist lookup failed for {name}: {e}")
        return None


async def _discover_from_pubdev(name: str) -> dict | None:
    """Query pub.dev API for Dart/Flutter package metadata."""
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(f"https://pub.dev/api/packages/{name}")
            if resp.status_code != 200:
                return None
            data = resp.json()
            latest = data.get("latest", {})
            pubspec = latest.get("pubspec", {})
            docs_url = pubspec.get("documentation") or pubspec.get("homepage") or ""
            repo_url = pubspec.get("repository") or ""
            # Fallback: pub.dev documentation page
            if not docs_url:
                docs_url = f"https://pub.dev/documentation/{name}/latest/"
            return {
                "name": pubspec.get("name", name),
                "description": pubspec.get("description") or "",
                "homepage": docs_url,
                "repository": repo_url,
                "registry": "pubdev",
            }
    except Exception as e:
        logger.debug(f"pub.dev lookup failed for {name}: {e}")
        return None


async def _discover_from_rubygems(name: str) -> dict | None:
    """Query RubyGems API for Ruby gem metadata."""
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(f"https://rubygems.org/api/v1/gems/{name}.json")
            if resp.status_code != 200:
                return None
            data = resp.json()
            docs_url = data.get("documentation_uri") or data.get("homepage_uri") or ""
            repo_url = data.get("source_code_uri") or ""
            # Fallback: extract GitHub URL from any URI field
            if not repo_url or "github.com" not in repo_url:
                for key in ("homepage_uri", "bug_tracker_uri", "changelog_uri"):
                    val = data.get(key) or ""
                    if "github.com" in val:
                        repo_url = val
                        break
            return {
                "name": data.get("name", name),
                "description": data.get("info") or "",
                "homepage": docs_url,
                "repository": repo_url,
                "registry": "rubygems",
                "downloads": data.get("downloads", 0),
            }
    except Exception as e:
        logger.debug(f"RubyGems lookup failed for {name}: {e}")
        return None


async def _discover_from_nuget(name: str) -> dict | None:
    """Query NuGet API for .NET/C# package metadata."""
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            # NuGet service index → registration endpoint
            resp = await client.get(
                f"https://api.nuget.org/v3/registration5-gz-semver2/{name.lower()}/index.json",
                headers={"Accept": "application/json"},
            )
            if resp.status_code != 200:
                return None
            data = resp.json()
            # Get the latest catalog entry
            pages = data.get("items", [])
            if not pages:
                return None
            last_page = pages[-1]
            items = last_page.get("items")
            if not items:
                # Need to fetch the page
                page_url = last_page.get("@id")
                if page_url:
                    page_resp = await client.get(page_url)
                    if page_resp.status_code == 200:
                        items = page_resp.json().get("items", [])
            if not items:
                return None
            latest = items[-1].get("catalogEntry", {})
            project_url = latest.get("projectUrl") or ""
            repo_url = ""
            # Extract GitHub repo from project URL if available
            if project_url and "github.com" in project_url:
                repo_url = project_url
            return {
                "name": latest.get("id", name),
                "description": latest.get("description") or "",
                "homepage": project_url,
                "repository": repo_url,
                "registry": "nuget",
            }
    except Exception as e:
        logger.debug(f"NuGet lookup failed for {name}: {e}")
        return None


async def _discover_from_maven(name: str) -> dict | None:
    """Query Maven Central for Java/Kotlin/Scala package metadata.

    ``name`` can be:
    - ``artifactId`` only (e.g. "guice") — searches all groups
    - ``groupId:artifactId`` (e.g. "com.google.inject:guice") — exact lookup
    """
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            if ":" in name:
                group_id, artifact_id = name.split(":", 1)
                q = f'g:"{group_id}" AND a:"{artifact_id}"'
            else:
                q = f'a:"{name}"'
            resp = await client.get(
                "https://search.maven.org/solrsearch/select",
                params={"q": q, "rows": 5, "wt": "json"},
            )
            if resp.status_code != 200:
                return None
            docs = resp.json().get("response", {}).get("docs", [])
            if not docs:
                return None
            # Prefer exact artifactId match
            name_lower = name.split(":")[-1].lower() if ":" in name else name.lower()
            best = None
            for doc in docs:
                if doc.get("a", "").lower() == name_lower:
                    best = doc
                    break
            if not best:
                best = docs[0]
            group_id = best.get("g", "")
            artifact_id = best.get("a", "")
            # Build javadoc URL (standard Maven Central pattern)
            version = best.get("latestVersion") or best.get("v", "")
            homepage = ""
            if group_id and artifact_id and version:
                homepage = (
                    f"https://javadoc.io/doc/" f"{group_id}/{artifact_id}/{version}"
                )
            repo_url = ""
            # Try to find GitHub repo from scm info via additional API call
            if group_id and artifact_id and version:
                try:
                    pom_url = (
                        f"https://search.maven.org/solrsearch/select"
                        f"?q=g:{group_id}+AND+a:{artifact_id}+AND+v:{version}"
                        f"&rows=1&wt=json"
                    )
                    pom_resp = await client.get(pom_url)
                    if pom_resp.status_code == 200:
                        pom_docs = pom_resp.json().get("response", {}).get("docs", [])
                        if pom_docs:
                            # ec field contains extra info in some responses
                            pass
                except Exception:
                    pass
            return {
                "name": f"{group_id}:{artifact_id}" if group_id else name,
                "description": "",
                "homepage": homepage,
                "repository": repo_url,
                "registry": "maven",
            }
    except Exception as e:
        logger.debug(f"Maven Central lookup failed for {name}: {e}")
        return None


# Map canonical language names to GitHub language filters.
# GitHub uses specific casing/naming for its language: filter.
_GITHUB_LANGUAGE_NAMES: dict[str, str] = {
    "python": "python",
    "javascript": "javascript",
    "typescript": "typescript",
    "rust": "rust",
    "go": "go",
    "java": "java",
    "kotlin": "kotlin",
    "csharp": "c#",
    "php": "php",
    "ruby": "ruby",
    "swift": "swift",
    "c": "c",
    "cpp": "c++",
    "zig": "zig",
    "dart": "dart",
    "elixir": "elixir",
    "haskell": "haskell",
    "scala": "scala",
    "lua": "lua",
    "perl": "perl",
    "r": "r",
    "julia": "julia",
    "nim": "nim",
    "ocaml": "ocaml",
    "clojure": "clojure",
    "erlang": "erlang",
}


# Map of user-facing languages to acceptable GitHub primary languages.
# Many libraries have a primary GitHub language that differs from the
# language developers use to write code with them (e.g. nokogiri is a
# Ruby gem whose GitHub primary language is C because of native extensions).
_GITHUB_LANGUAGE_ACCEPT: dict[str, set[str]] = {
    "java": {"java", "groovy", "kotlin", "html", "javascript"},
    "kotlin": {"kotlin", "java"},
    "csharp": {"c#", "f#"},
    "php": {"php", "c", "c++"},
    "ruby": {"ruby", "c", "c++"},
    "swift": {"swift", "objective-c", "objective-c++", "c"},
    "lua": {"lua", "c", "c++", "objective-c", "moonscript"},
    "erlang": {"erlang", "elixir", "javascript"},
    "elixir": {"elixir", "erlang"},
    "dart": {"dart", "c++"},
    "cpp": {"c++", "c"},
    "c": {"c", "c++"},
    "rust": {"rust", "zig"},
    "go": {"go", "typescript", "javascript"},
    "scala": {"scala", "java"},
    "javascript": {"javascript", "typescript"},
    "typescript": {"typescript", "javascript"},
    "ocaml": {"ocaml", "reason"},
    "zig": {"zig", "c", "c++"},
    "haskell": {"haskell"},
    "nim": {"nim"},
    "clojure": {"clojure", "java"},
    "perl": {"perl"},
    "r": {"r"},
    "julia": {"julia"},
}


async def _discover_from_github_search(name: str, language: str) -> dict | None:
    """Search GitHub for a library repo by name and language.

    Generic fallback for languages without a dedicated package registry
    (Java, PHP, Ruby, Swift, Kotlin, C#, Dart, Elixir, etc.).

    Uses the GitHub search API sorted by stars.  Two passes:
      1. With ``language:{lang}`` filter — fast, targeted.
      2. Without the language filter — catches repos whose *primary*
         GitHub language differs from the user-facing language (e.g.
         nokogiri is Ruby but GitHub marks it as C).

    Language verification is relaxed: instead of requiring the primary
    language to match exactly, we accept members of the
    ``_GITHUB_LANGUAGE_ACCEPT`` set, and very popular repos (>=5 000
    stars) are accepted with no language check at all.
    """
    gh_lang = _GITHUB_LANGUAGE_NAMES.get(language)
    if not gh_lang:
        return None

    # For scoped names like "gorilla/mux", search the last part
    search_name = name.split("/")[-1] if "/" in name else name
    name_lower = name.lower()

    # Languages accepted for this user-facing language
    accept_langs = _GITHUB_LANGUAGE_ACCEPT.get(language, {gh_lang.lower()})

    async def _search_github(query: str) -> list[dict]:
        """Execute a single GitHub search and return items."""
        try:
            async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
                resp = await client.get(
                    "https://api.github.com/search/repositories",
                    params={
                        "q": query,
                        "sort": "stars",
                        "per_page": 10,
                    },
                    headers=_github_headers(),
                )
                if resp.status_code != 200:
                    logger.debug(
                        f"GitHub search returned {resp.status_code} for q={query}"
                    )
                    return []
                return resp.json().get("items", [])
        except Exception as e:
            logger.debug(f"GitHub search failed for q={query}: {e}")
            return []

    def _is_lang_ok(repo_lang: str, stars: int) -> bool:
        """Check if repository language is acceptable."""
        lang = repo_lang.lower()
        # Very popular repos are always accepted (>= 5000 stars)
        if stars >= 5000:
            return True
        # Otherwise, must be in the accept set
        return lang in accept_langs

    def _build_result(item: dict, match_type: str) -> dict:
        """Build a discovery result dict from a GitHub API item."""
        homepage = item.get("homepage") or ""
        repo_url = item.get("html_url") or ""
        stars = item.get("stargazers_count", 0)
        docs_url = (
            homepage
            if (homepage and "github.com" not in homepage.lower())
            else repo_url
        )
        logger.info(
            f"GitHub search {match_type} {name} ({language}): "
            f"{repo_url} ({stars} stars)"
        )
        return {
            "name": name,
            "description": item.get("description") or "",
            "homepage": docs_url,
            "repository": repo_url,
            "registry": "github",
            "stars": stars,
        }

    # Build search queries:
    #   Pass 1: primary language filter  (e.g. ``language:elixir``)
    #   Pass 1b…: alt-language filters   (e.g. ``language:erlang`` for elixir)
    #   Pass 2: no language filter        (catches very popular mismatches)
    queries = [f"{search_name} language:{gh_lang}"]
    for alt in sorted(accept_langs):
        alt_gh = _GITHUB_LANGUAGE_NAMES.get(alt) or alt
        if alt_gh.lower() != gh_lang.lower():
            queries.append(f"{search_name} language:{alt_gh}")
    queries.append(search_name)

    for query in queries:
        items = await _search_github(query)
        if not items:
            continue

        # Exact name match
        for item in items:
            repo_name = item.get("name", "").lower()
            full_name = item.get("full_name", "").lower()

            if "/" in name_lower:
                name_match = full_name == name_lower
            else:
                name_match = repo_name == name_lower

            if not name_match:
                continue

            repo_lang = item.get("language") or ""
            stars = item.get("stargazers_count", 0)

            if not _is_lang_ok(repo_lang, stars):
                continue
            if stars < 20:
                continue

            return _build_result(item, "found")

        # Fuzzy match: name contained in repo name (top result only)
        top = items[0]
        top_name = top.get("name", "").lower()
        top_lang = top.get("language") or ""
        top_stars = top.get("stargazers_count", 0)

        if (
            _is_lang_ok(top_lang, top_stars)
            and top_stars >= 100
            and (
                name_lower in top_name
                or top_name in name_lower
                or name_lower.replace("-", "") == top_name.replace("-", "")
            )
        ):
            return _build_result(top, "fuzzy match")

    return None


async def _get_github_homepage(url: str) -> str | None:
    """Fetch the GitHub repository's homepage URL via the API.

    When a package registry (npm) lists a GitHub URL as the homepage
    (e.g. ``github.com/vuejs/core/tree/main/packages/vue#readme``),
    the repo often has a dedicated docs site in its ``homepage`` field
    (e.g. ``https://vuejs.org/``).

    Returns the homepage URL if it's non-GitHub, else None.
    """
    # Extract owner/repo from various GitHub URL formats
    cleaned = url.replace("git+", "").replace(".git", "")
    m = re.search(r"github\.com[/:]([^/]+)/([^/#?]+)", cleaned)
    if not m:
        return None
    owner, repo = m.group(1), m.group(2)

    try:
        async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
            resp = await client.get(
                f"https://api.github.com/repos/{owner}/{repo}",
                headers=_github_headers(),
            )
            if resp.status_code != 200:
                return None
            data = resp.json()
            gh_homepage = data.get("homepage", "")
            if gh_homepage and "github.com" not in gh_homepage.lower():
                # Filter registry listing pages (uninformative, not docs)
                gh_lower = gh_homepage.lower()
                if any(
                    reg in gh_lower
                    for reg in (
                        "crates.io/crates/",
                        "pypi.org/project/",
                        "npmjs.com/package/",
                    )
                ):
                    return None
                return gh_homepage.rstrip("/")
    except Exception as e:
        logger.debug(f"GitHub homepage check failed for {owner}/{repo}: {e}")

    return None


async def _probe_docs_url(homepage: str, lib_name: str, registry: str = "") -> str:
    """Probe for a better documentation URL than the project homepage.

    Many libraries list their marketing/landing page in package registries,
    but actual documentation lives at a different URL:

    - ``docs.{domain}`` subdomain (e.g., docs.solidjs.com, docs.nestjs.com)
    - ``{name}.readthedocs.io`` (validated via ``objects.inv`` project name)
    - ``{homepage}/docs/`` path (e.g., remix.run/docs/)

    Probes these alternatives in parallel. Returns the best URL found,
    preferring URLs with Sphinx ``objects.inv`` (guaranteed rich docs).
    Falls back to ``homepage`` if no better alternative exists.

    ReadTheDocs results are validated by parsing the ``objects.inv`` header
    project name — must match the library name to prevent false positives
    (e.g., ``chi.readthedocs.io`` being an unrelated Python project).
    """
    parsed = urlparse(homepage)
    netloc = parsed.netloc
    base_domain = netloc.removeprefix("www.") if netloc.startswith("www.") else netloc
    # Normalize lib name for probing:
    # "@nestjs/core" → scope="nestjs", pkg="core"
    # "solid-js" → scope="", pkg="solid-js"
    scope_part = ""
    pkg_part = lib_name.lower().lstrip("@")
    if "/" in pkg_part:
        scope_part = pkg_part.split("/")[0]
        pkg_part = pkg_part.split("/")[-1]
    clean_name = pkg_part
    # Normalized for matching (no hyphens/underscores)
    clean_name_norm = clean_name.replace("-", "").replace("_", "")
    # Generic package names that collide with unrelated RTD projects
    _GENERIC_NAMES = frozenset(
        {
            "core",
            "react",
            "cli",
            "common",
            "utils",
            "types",
            "client",
            "server",
            "api",
            "app",
            "config",
            "test",
            "ui",
            "web",
        }
    )

    candidates: list[tuple[str, str]] = []

    # 1. docs.{domain} subdomain — skip for generic hosting domains
    # (docs.github.com is GitHub's own docs, not project docs)
    # (docs.pypi.org is PyPI's own API docs, not project docs)
    _skip_docs_subdomain = {
        "github.com",
        "github.io",
        "gitlab.com",
        "bitbucket.org",
        "pypi.org",
        "npmjs.com",
        "npmjs.org",
        "crates.io",
    }
    if not base_domain.startswith("docs.") and base_domain not in _skip_docs_subdomain:
        candidates.append(("docs_subdomain", f"https://docs.{base_domain}/"))

    # 2. ReadTheDocs: probe {name}.readthedocs.io when not already on RTD.
    # Skip for generic package names and very short names (<=4 chars).
    # Skip for non-Python registries (npm, crates, go) — RTD is almost
    # exclusively used by Python projects, so probing for React/Rust/Go
    # libs would match unrelated Python packages with the same name.
    # Validated via objects.inv: project name must match + object count >= 50
    # to reject squatter/placeholder projects (real docs have 50+ objects).
    _rtd_skip_registries = {"npm", "crates", "go"}
    if (
        "readthedocs" not in base_domain
        and clean_name not in _GENERIC_NAMES
        and registry not in _rtd_skip_registries
    ):
        rtd_name = scope_part or clean_name
        if len(rtd_name) > 4:
            candidates.append(
                ("readthedocs", f"https://{rtd_name}.readthedocs.io/en/latest/")
            )

    # 3. {homepage}/docs/ path (only if homepage has no path or short path)
    if len(parsed.path.strip("/")) <= 1:
        docs_path_url = f"{parsed.scheme}://{parsed.netloc}/docs/"
        candidates.append(("docs_path", docs_path_url))

    if not candidates:
        return homepage

    async def _check(label: str, url: str) -> tuple[str, str, int, bool] | None:
        try:
            async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
                resp = await client.get(url)
                if resp.status_code != 200:
                    return None
                content = resp.text
                content_len = len(content)
                # Must be substantial HTML/text, not an error page
                if content_len < 500:
                    return None
                final_url = str(resp.url)
                # Reject login/auth/account pages (false positive redirects)
                final_path = urlparse(final_url).path.lower()
                _auth_segments = (
                    "/login",
                    "/signin",
                    "/signup",
                    "/account",
                    "/auth",
                    "/register",
                )
                if any(seg in final_path for seg in _auth_segments):
                    return None
                # Avoid redirect loops back to the original homepage
                if urlparse(final_url).netloc == parsed.netloc and label != "docs_path":
                    final_parsed = urlparse(final_url)
                    if not final_parsed.path.startswith("/docs"):
                        if "docs" not in final_parsed.netloc:
                            return None
                # Check for objects.inv (Sphinx docs indicator)
                has_inv = False
                inv_url = final_url.rstrip("/") + "/objects.inv"
                try:
                    inv_resp = await client.get(inv_url)
                    if inv_resp.status_code == 200 and inv_resp.content[:30].startswith(
                        b"# Sphinx inventory version"
                    ):
                        # For ReadTheDocs: validate project name matches lib
                        # and has enough objects (>= 50) to be real docs,
                        # not a squatter/placeholder project.
                        if label == "readthedocs":
                            inv_content = inv_resp.content
                            inv_text = inv_content[:500].decode(
                                "utf-8", errors="replace"
                            )
                            proj_match = re.search(
                                r"^# Project:\s*(.+)$", inv_text, re.MULTILINE
                            )
                            if proj_match:
                                proj_name = (
                                    proj_match.group(1)
                                    .strip()
                                    .lower()
                                    .replace("-", "")
                                    .replace("_", "")
                                    .replace(" ", "")
                                )
                                if clean_name_norm not in proj_name:
                                    logger.debug(
                                        f"RTD project '{proj_match.group(1).strip()}'"
                                        f" doesn't match '{lib_name}', skipping"
                                    )
                                    return None
                            # Count objects: real docs have 50+, squatters < 30
                            try:
                                # Find end of header (4 lines starting with #)
                                hdr_pos = 0
                                for _ in range(4):
                                    hdr_pos = inv_content.index(b"\n", hdr_pos) + 1
                                decompressed = zlib.decompress(inv_content[hdr_pos:])
                                obj_count = len(decompressed.split(b"\n")) - 1
                                if obj_count < 50:
                                    logger.debug(
                                        f"RTD {lib_name}: only {obj_count} "
                                        f"objects, likely squatter — skipping"
                                    )
                                    return None
                            except Exception:
                                # Can't count objects — reject for safety
                                return None
                        has_inv = True
                except Exception:
                    pass
                # ReadTheDocs without objects.inv is unreliable — skip
                if label == "readthedocs" and not has_inv:
                    return None
                return (label, final_url, content_len, has_inv)
        except Exception:
            return None

    results = await asyncio.gather(
        *[_check(label, url) for label, url in candidates],
        return_exceptions=True,
    )

    valid = [r for r in results if isinstance(r, tuple)]
    if not valid:
        return homepage

    # Pick best: objects.inv > large content > small content
    best: tuple[str, str] | None = None
    best_score = 0
    for label, final_url, size, has_inv in valid:
        score = 0
        if has_inv:
            score += 100  # Sphinx docs = gold standard
        if size > 10000:
            score += 10
        elif size > 2000:
            score += 5
        elif size > 500:
            score += 2
        # docs subdomain gets small bonus (same org, high confidence)
        if label == "docs_subdomain":
            score += 3
        if score > best_score:
            best_score = score
            best = (label, final_url)

    if best:
        logger.info(
            f"Probed better docs URL for {lib_name}: {best[1]} "
            f"(via {best[0]}, score={best_score})"
        )
        return best[1]

    return homepage


# ---------------------------------------------------------------------------
# Language → registry mapping for targeted discovery
# ---------------------------------------------------------------------------

_LANGUAGE_ALIASES: dict[str, str] = {
    "py": "python",
    "js": "javascript",
    "ts": "typescript",
    "node": "javascript",
    "nodejs": "javascript",
    "rs": "rust",
    "golang": "go",
    "kt": "kotlin",
    "c#": "csharp",
    "dotnet": "csharp",
    ".net": "csharp",
    "c++": "cpp",
    "rb": "ruby",
}

# Map normalized language to supported registries.
# Empty list = language known but no registry integration (use SearXNG).
_LANGUAGE_REGISTRIES: dict[str, list[str]] = {
    "python": ["pypi"],
    "javascript": ["npm"],
    "typescript": ["npm"],
    "rust": ["crates"],
    "go": ["go"],
    "java": ["maven"],
    "kotlin": ["maven"],
    "scala": ["maven"],
    "csharp": ["nuget"],
    "php": ["packagist"],
    "ruby": ["rubygems"],
    "dart": ["pubdev"],
    "elixir": ["hex"],
    "erlang": ["hex"],
    # Languages without integrated registry — use GitHub search fallback
    "swift": [],
    "c": [],
    "cpp": [],
    "zig": [],
    "haskell": [],
    "lua": [],
    "perl": [],
    "r": [],
    "julia": [],
    "clojure": [],
    "nim": [],
    "ocaml": [],
}

# Registry name → discovery function
_REGISTRY_FUNCTIONS: dict[str, Any] = {
    "npm": _discover_from_npm,
    "pypi": _discover_from_pypi,
    "crates": _discover_from_crates,
    "go": _discover_from_go,
    "hex": _discover_from_hex,
    "packagist": _discover_from_packagist,
    "pubdev": _discover_from_pubdev,
    "rubygems": _discover_from_rubygems,
    "nuget": _discover_from_nuget,
    "maven": _discover_from_maven,
}


def _normalize_language(language: str) -> str:
    """Normalize language name to canonical form."""
    lang = language.strip().lower()
    return _LANGUAGE_ALIASES.get(lang, lang)


# ---------------------------------------------------------------------------
# Well-known docs — ONLY for genuinely ambiguous names, monorepo
# sub-frameworks, and non-library tools/platforms that no registry can
# discover correctly.  Entries should be minimal — add a new registry
# instead of adding entries here.
# ---------------------------------------------------------------------------
_WELL_KNOWN_DOCS: dict[str, dict[str, str]] = {
    # --- Ambiguous names (multi-language collision) ---
    "boost": {
        "homepage": "https://www.boost.org/doc/libs/",
        "repository": "https://github.com/boostorg/boost",
        "description": "Boost C++ Libraries — portable, peer-reviewed",
    },
    "cmake": {
        "homepage": "https://cmake.org/cmake/help/latest/",
        "repository": "https://github.com/Kitware/CMake",
        "description": "CMake cross-platform build system",
    },
    "protobuf": {
        "homepage": "https://protobuf.dev/",
        "repository": "https://github.com/protocolbuffers/protobuf",
        "description": "Protocol Buffers — Google's data interchange format",
    },
    "flux": {
        "homepage": "https://fluxcd.io/flux/",
        "repository": "https://github.com/fluxcd/flux2",
        "description": "Flux — GitOps toolkit for Kubernetes",
    },
    # --- Java/Spring monorepo sub-frameworks ---
    "spring-webflux": {
        "homepage": "https://docs.spring.io/spring-framework/reference/web/webflux.html",
        "repository": "https://github.com/spring-projects/spring-framework",
        "description": "Spring WebFlux — reactive web framework for Java",
    },
    "kafka-streams": {
        "homepage": "https://kafka.apache.org/documentation/streams/",
        "repository": "https://github.com/apache/kafka",
        "description": "Apache Kafka Streams — stream processing library",
    },
    "reactor-test": {
        "homepage": "https://projectreactor.io/docs/core/release/reference/#testing",
        "repository": "https://github.com/reactor/reactor-core",
        "description": "Project Reactor test utilities — StepVerifier",
    },
    # --- Android Jetpack monorepo ---
    "navigation-compose": {
        "homepage": "https://developer.android.com/develop/ui/compose/navigation",
        "repository": "https://github.com/androidx/androidx",
        "description": "Jetpack Navigation for Compose",
    },
    "work-manager": {
        "homepage": "https://developer.android.com/develop/background-work/background-tasks/persistent/getting-started",
        "repository": "https://github.com/androidx/androidx",
        "description": "Android WorkManager — background task scheduling",
    },
    "datastore": {
        "homepage": "https://developer.android.com/topic/libraries/architecture/datastore",
        "repository": "https://github.com/androidx/androidx",
        "description": "Android Jetpack DataStore — data storage solution",
    },
    # --- Non-library tools/platforms ---
    "gitlab-ci": {
        "homepage": "https://docs.gitlab.com/ci/yaml/",
        "repository": "https://github.com/gitlabhq/gitlabhq",
        "description": "GitLab CI/CD pipeline configuration",
    },
    "linkerd": {
        "homepage": "https://linkerd.io/2/reference/",
        "repository": "https://github.com/linkerd/linkerd2",
        "description": "Linkerd — ultra-light service mesh for Kubernetes",
    },
    "apisix": {
        "homepage": "https://apisix.apache.org/docs/apisix/getting-started/",
        "repository": "https://github.com/apache/apisix",
        "description": "Apache APISIX — cloud-native API gateway",
    },
    "krakend": {
        "homepage": "https://www.krakend.io/docs/overview/",
        "repository": "https://github.com/krakend/krakend-ce",
        "description": "KrakenD — high-performance API gateway",
    },
    "defold": {
        "homepage": "https://defold.com/manuals/introduction/",
        "repository": "https://github.com/defold/defold",
        "description": "Defold — cross-platform game engine",
    },
    "sqitch": {
        "homepage": "https://sqitch.org/docs/",
        "repository": "https://github.com/sqitchers/sqitch",
        "description": "Sqitch — database change management",
    },
    "tekton": {
        "homepage": "https://tekton.dev/docs/",
        "repository": "https://github.com/tektoncd/pipeline",
        "description": "Tekton — Kubernetes-native CI/CD pipelines",
    },
    "spline": {
        "homepage": "https://docs.spline.design/",
        "repository": "",
        "description": "Spline — 3D design tool for the web",
    },
    "dhall": {
        "homepage": "https://dhall-lang.org/",
        "repository": "https://github.com/dhall-lang/dhall-haskell",
        "description": "Dhall — programmable configuration language",
    },
    "@enhance/ssr": {
        "homepage": "https://enhance.dev/docs/",
        "repository": "https://github.com/enhance-dev/enhance",
        "description": "Enhance — HTML-first web framework",
    },
    # --- Go tools (binaries, not importable packages) ---
    "staticcheck": {
        "homepage": "https://staticcheck.dev/docs/",
        "repository": "https://github.com/dominikh/go-tools",
        "description": "Staticcheck — Go static analysis tool",
    },
    "mockgen": {
        "homepage": "https://pkg.go.dev/go.uber.org/mock/mockgen",
        "repository": "https://github.com/uber-go/mock",
        "description": "MockGen — Go mock code generator",
    },
    "govulncheck": {
        "homepage": "https://pkg.go.dev/golang.org/x/vuln/cmd/govulncheck",
        "repository": "https://github.com/golang/vuln",
        "description": "govulncheck — Go vulnerability scanner",
    },
}


async def discover_library(name: str, language: str | None = None) -> dict | None:
    """Discover library metadata from package registries.

    Queries all supported registries in parallel. Scores by:
    1. Exact name match (case-insensitive)
    2. Has valid docs/homepage URL
    3. Non-GitHub homepage (custom domain = established project)
    4. Description length (longer = more established)
    5. Dedicated docs URL pattern (readthedocs, docs.*, etc.)

    Supported registries:
    - npm (JavaScript/TypeScript)
    - PyPI (Python)
    - crates.io (Rust)
    - Go modules (Go)
    - Maven Central (Java/Kotlin/Scala)
    - Hex.pm (Elixir/Erlang)
    - Packagist (PHP)
    - pub.dev (Dart/Flutter)
    - RubyGems (Ruby)
    - NuGet (C#/.NET)

    When ``language`` is specified, only queries matching registries.
    This prevents e.g. npm's obscure "fastapi" package from shadowing
    Python's FastAPI, or npm "torch" from shadowing PyTorch.
    """
    # -------------------------------------------------------------------
    # Priority 0: Well-known docs — handles tools/platforms not on standard
    # registries, sub-frameworks, and libraries with generic names that
    # cause wrong discovery (e.g. "boost" → xgboost, "protobuf" → npm pkg).
    # -------------------------------------------------------------------
    well_known = _WELL_KNOWN_DOCS.get(name.lower())
    if well_known:
        logger.info(f"Using well-known docs for {name}: {well_known['homepage']}")
        return {**well_known, "name": name, "registry": "well_known"}

    # Build registry tasks based on language filter
    if language:
        lang = _normalize_language(language)
        registry_names = _LANGUAGE_REGISTRIES.get(lang)
        if registry_names is not None:
            if not registry_names:
                # Known language but no registry — try GitHub search
                logger.info(
                    f"No registry for language '{language}', "
                    "trying GitHub search fallback"
                )
                gh_result = await _discover_from_github_search(name, lang)
                if gh_result:
                    # Probe for better docs URL
                    homepage = gh_result.get("homepage", "")
                    if homepage and "github.com" not in urlparse(homepage).netloc:
                        probed = await _probe_docs_url(
                            homepage, name, registry="github"
                        )
                        if probed != homepage:
                            logger.info(f"Probed {name} docs: {homepage} -> {probed}")
                            gh_result["homepage"] = probed
                    # Try to upgrade GitHub-only homepage via API
                    repo_url = gh_result.get("repository", "")
                    if (
                        homepage
                        and "github.com" in urlparse(homepage).netloc
                        and repo_url
                    ):
                        gh_hp = await _get_github_homepage(repo_url)
                        if gh_hp:
                            logger.info(
                                f"Upgraded {name} homepage: {homepage} -> {gh_hp}"
                            )
                            gh_result["homepage"] = gh_hp
                    return gh_result
                # GitHub search failed — let SearXNG handle
                return None
            # Query only matching registries
            tasks = [
                _REGISTRY_FUNCTIONS[r](name)
                for r in registry_names
                if r in _REGISTRY_FUNCTIONS
            ]
        else:
            # Unknown language — query all registries as fallback
            tasks = [
                _discover_from_npm(name),
                _discover_from_pypi(name),
                _discover_from_crates(name),
                _discover_from_go(name),
                _discover_from_hex(name),
                _discover_from_packagist(name),
                _discover_from_pubdev(name),
                _discover_from_rubygems(name),
                _discover_from_nuget(name),
                _discover_from_maven(name),
            ]
    else:
        # No language specified — query all registries (default)
        tasks = [
            _discover_from_npm(name),
            _discover_from_pypi(name),
            _discover_from_crates(name),
            _discover_from_go(name),
            _discover_from_hex(name),
            _discover_from_packagist(name),
            _discover_from_pubdev(name),
            _discover_from_rubygems(name),
            _discover_from_nuget(name),
            _discover_from_maven(name),
        ]

    results = await asyncio.gather(*tasks, return_exceptions=True)

    # Pre-upgrade: for results with a GitHub homepage or repo but no
    # non-GitHub homepage, try to fill homepage from the GitHub API
    # before scoring.  This catches PyPI packages that only list their
    # GitHub page as "homepage" (e.g. crawl4ai → crawl4ai.com).
    upgrade_tasks = []
    upgrade_indices = []
    valid_results = [r for r in results if isinstance(r, dict)]
    for i, r in enumerate(valid_results):
        homepage = r.get("homepage") or ""
        repo_url = r.get("repository") or ""
        hp_is_github = "github.com" in homepage
        # Upgrade when NO homepage at all, OR homepage IS a GitHub URL
        if (not homepage or hp_is_github) and (repo_url or homepage):
            gh_url = repo_url if "github.com" in repo_url else homepage
            if "github.com" in gh_url:
                upgrade_tasks.append(_get_github_homepage(gh_url))
                upgrade_indices.append(i)

    if upgrade_tasks:
        gh_results = await asyncio.gather(*upgrade_tasks, return_exceptions=True)
        for idx, gh_hp in zip(upgrade_indices, gh_results, strict=False):
            if isinstance(gh_hp, str) and gh_hp:
                valid_results[idx]["homepage"] = gh_hp
                logger.debug(
                    f"Pre-upgraded {valid_results[idx].get('name')}"
                    f" homepage from GitHub: {gh_hp}"
                )

    # Score each result for relevance
    scored: list[tuple[int, dict]] = []
    for r in valid_results:
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
                lib_norm = name.lower().replace("-", "")
                if parsed_hp.netloc in ("docs.rs", "pkg.go.dev"):
                    score += 1  # Auto-generated docs, minimal boost
                    # Don't give name-in-path bonus: always true for these
                else:
                    score += 3
                    # Library name appears in the domain → likely official site
                    # e.g. fastapi.tiangolo.com, pytorch.org, react.dev
                    host_norm = parsed_hp.netloc.lower().replace("-", "")
                    if lib_norm in host_norm:
                        score += 3
                # ReadTheDocs bonus: only when subdomain exactly matches lib name
                # Prevents e.g. "app-turbo.readthedocs.org" scoring for "turbo"
                if any(p in parsed_hp.netloc for p in ("readthedocs", "rtfd.io")):
                    subdomain = parsed_hp.netloc.split(".")[0].lower().replace("-", "")
                    if subdomain == lib_norm:
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

        # Penalize deprecated packages (npm deprecate-holder, squatted names)
        if r.get("deprecated"):
            score -= 20

        # Penalize known placeholder/junk homepage patterns
        all_urls = ((homepage or "") + " " + (r.get("repository") or "")).lower()
        if any(p in all_urls for p in ("deprecate-holder", "placeholder")):
            score -= 15

        # Penalize crates.io auto-generated docs.rs fallback URLs
        if r.get("docs_rs_fallback"):
            score -= 2

        # Popularity boost for packages with star count data (Go, GitHub)
        # Helps disambiguate generic names like "echo", "gin", etc.
        stars = r.get("stars", 0)
        if stars >= 10000:
            score += 3
        elif stars >= 1000:
            score += 2
        elif stars >= 100:
            score += 1

        # Download count boost for crates.io packages
        # Helps disambiguate generic names: clap (668M), diesel (22M), etc.
        # Higher bonuses than stars because download counts are more reliable
        # for popularity (no manual curation needed).
        downloads = r.get("downloads", 0)
        if downloads >= 50_000_000:
            score += 5
        elif downloads >= 5_000_000:
            score += 3
        elif downloads >= 500_000:
            score += 1

        # Registry trust: npm/PyPI are direct package registries (exact API match),
        # while Go uses GitHub search (may return tangentially related repos).
        # Give primary registries a small bonus to break ties.
        reg = r.get("registry", "")
        if reg in ("npm", "pypi"):
            score += 2

        scored.append((score, r))

    # Sort by score descending, pick best
    scored.sort(key=lambda x: x[0], reverse=True)

    if scored:
        best_score, best = scored[0]

        # GitHub homepage upgrade: when the homepage is a GitHub URL,
        # check the GitHub API for a better homepage (e.g. vuejs.org).
        homepage = best.get("homepage", "")
        repo_url = best.get("repository", "")
        if homepage and "github.com" in urlparse(homepage).netloc:
            # Try to extract owner/repo from either homepage or repo URL
            gh_url = repo_url if repo_url else homepage
            gh_homepage = await _get_github_homepage(gh_url)
            if gh_homepage:
                logger.info(f"Upgraded {name} homepage: {homepage} -> {gh_homepage}")
                best["homepage"] = gh_homepage

        if best.get("homepage"):
            # Probe for better docs URL (docs subdomain, ReadTheDocs, /docs/)
            original_hp = best["homepage"]
            probed_url = await _probe_docs_url(
                original_hp, name, registry=best.get("registry", "")
            )
            if probed_url != original_hp:
                logger.info(f"Upgraded {name} docs URL: {original_hp} -> {probed_url}")
                best["homepage"] = probed_url

            logger.info(
                f"Discovered {name} docs: {best['homepage']} "
                f"(via {best['registry']}, score={best_score})"
            )
            return best
        # No homepage but has some data
        return best

    # All registries failed — try GitHub search as last resort
    if language:
        lang = _normalize_language(language)
        if lang in _GITHUB_LANGUAGE_NAMES:
            logger.info(
                f"All registries failed for {name} ({language}), "
                "trying GitHub search as last resort"
            )
            gh_result = await _discover_from_github_search(name, lang)
            if gh_result:
                homepage = gh_result.get("homepage", "")
                if homepage and "github.com" not in urlparse(homepage).netloc:
                    probed = await _probe_docs_url(homepage, name, registry="github")
                    if probed != homepage:
                        logger.info(f"Probed {name} docs: {homepage} -> {probed}")
                        gh_result["homepage"] = probed
                repo_url = gh_result.get("repository", "")
                if homepage and "github.com" in urlparse(homepage).netloc and repo_url:
                    gh_hp = await _get_github_homepage(repo_url)
                    if gh_hp:
                        logger.info(f"Upgraded {name} homepage: {homepage} -> {gh_hp}")
                        gh_result["homepage"] = gh_hp
                return gh_result

    return None


def _normalize_docs_url(url: str) -> str:
    """Normalize an overly-specific docs URL to a broader docs root.

    When a package registry returns a deeply nested page URL
    (e.g., ``/docs/stable/clients/python/overview``), normalize it to the
    docs root for better crawler coverage (e.g., ``/docs/stable/``).

    Only normalizes when there are 3+ path segments after a docs marker.
    """
    parsed = urlparse(url)
    path = parsed.path.rstrip("/")
    parts = path.split("/")

    doc_markers = ("docs", "doc", "documentation")
    for i, p in enumerate(parts):
        if p.lower() in doc_markers:
            remaining = len(parts) - i - 1
            if remaining >= 3:
                keep_up_to = i + 2  # docs + one level (version/section)
                normalized_path = "/".join(parts[:keep_up_to]) + "/"
                normalized = f"{parsed.scheme}://{parsed.netloc}{normalized_path}"
                logger.info(f"Normalized docs URL: {url} -> {normalized}")
                return normalized
            break

    return url


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
# Content cleaning — strip noise before chunking
# ---------------------------------------------------------------------------

# Badge/shield image patterns
_BADGE_RE = re.compile(
    r"!\[.*?\]\(https?://(?:img\.shields\.io|badge\.|badges\.|github\.com/.*?/badge).*?\)",
    re.IGNORECASE,
)
# YAML frontmatter (--- ... ---)
_FRONTMATTER_RE = re.compile(r"\A---\s*\n.*?\n---\s*\n", re.DOTALL)
# mkdocs admonition blocks (!!! note "Title" ... indented content)
_ADMONITION_RE = re.compile(
    r"^!!!?\s+(?:note|tip|warning|info|danger|example|quote|abstract|"
    r"success|failure|bug|todo|question|hint|caution|attention|important|seealso)"
    r"(?:\s+\"[^\"]*\")?\s*\n(?:(?:\s{4}|\t).*\n)*",
    re.MULTILINE | re.IGNORECASE,
)
# mkdocstrings directives (::: module.path)
_MKDOCSTRINGS_RE = re.compile(r"^:::.*$", re.MULTILINE)
# HTML tags (standalone, not inside code blocks)
_HTML_TAG_RE = re.compile(
    r"<(?!code|pre)[a-z][^>]*>|</(?!code|pre)[a-z][^>]*>", re.IGNORECASE
)
# TOC anchor links (- [Title](#anchor))
_TOC_LINK_RE = re.compile(r"^\s*[-*]\s*\[.*?\]\(#[^)]*\)\s*$", re.MULTILINE)
# Navigation line patterns
_NAV_RE = re.compile(
    r"^\s*(?:"
    r"\u2190 Previous|Next \u2192|Skip to (?:main )?content|"
    r"Table of [Cc]ontents|On this page|"
    r"Edit (?:this|on) (?:page|GitHub)|"
    r"Suggest (?:changes|edits)|"
    r"Was this (?:page|article) helpful\?|"
    r"\u2b50 Star (?:us|this)"
    r")",
    re.IGNORECASE,
)
# Footer boilerplate
_FOOTER_RE = re.compile(
    r"^\s*(?:"
    r"Built with|Powered by|Made with|Generated (?:by|with)|"
    r"Copyright\s*(?:\u00a9|\(c\))|\u00a9\s*\d{4}|"
    r"All [Rr]ights [Rr]eserved"
    r")",
    re.IGNORECASE,
)
# Navigation link line: bullet or number + markdown link with full URL
_NAV_LINK_LINE_RE = re.compile(
    r"^\s*[-*]\s+(?:\[.*?\]\s*)?\[.*?\]\(https?://.*?\)\s*$"
    r"|^\s*\d+\.\s+\[.*?\]\(https?://.*?\)\s*$",
)
# MkDocs UI artifacts that leak into crawled markdown
_MKDOCS_UI_RE = re.compile(
    r"^\s*(?:"
    r"Initializing search|Toggle (?:navigation|search)|Search"
    r"|Back to top|Share\b|Go to repository"
    r")\s*$",
    re.IGNORECASE,
)
# Minimum consecutive nav-link lines to consider it a navigation block
_NAV_BLOCK_MIN_LINES = 8


def _strip_nav_blocks(content: str) -> str:
    """Remove navigation sidebar blocks from crawled content.

    Detects blocks of 8+ consecutive lines that look like site navigation
    (bullet/numbered lists with full-URL markdown links) and removes them.
    This targets MkDocs Material sidebars, Sphinx toctrees, and similar
    navigation structures that leak into crawled markdown.
    """
    lines = content.splitlines()
    result: list[str] = []
    nav_block: list[str] = []

    for line in lines:
        if _NAV_LINK_LINE_RE.match(line):
            nav_block.append(line)
        else:
            if len(nav_block) >= _NAV_BLOCK_MIN_LINES:
                # Navigation block detected — discard it
                pass
            else:
                # Short link list — keep it (could be legitimate content)
                result.extend(nav_block)
            nav_block = []
            result.append(line)

    # Handle trailing nav block
    if len(nav_block) < _NAV_BLOCK_MIN_LINES:
        result.extend(nav_block)

    return "\n".join(result)


def _strip_nav_heading_blocks(content: str) -> str:
    """Remove navigation-like blocks of consecutive headings.

    Navigation sidebars from rendered HTML sometimes produce long sequences
    of same-level headings with no meaningful content between them::

        ## Flexbox & Grid
        ## Spacing
        ## Sizing
        ## Typography
        ## Tables

    When 5+ consecutive headings at the same level have <= 50 chars of text
    between them, they are stripped as navigation artifacts.
    """
    lines = content.splitlines()
    heading_re = re.compile(r"^(#{1,6})\s+(.+)$")

    # Build heading map: line_index -> (level, text)
    headings: dict[int, tuple[int, str]] = {}
    for i, line in enumerate(lines):
        m = heading_re.match(line.lstrip())
        if m:
            headings[i] = (len(m.group(1)), m.group(2))

    if len(headings) < 5:
        return content

    # Find runs of same-level headings with minimal content between them
    nav_lines: set[int] = set()
    heading_indices = sorted(headings.keys())

    i = 0
    while i < len(heading_indices):
        start_idx = heading_indices[i]
        level = headings[start_idx][0]
        run = [start_idx]

        j = i + 1
        while j < len(heading_indices):
            idx = heading_indices[j]
            if headings[idx][0] != level:
                break
            # Content between this heading and previous must be minimal
            prev_idx = run[-1]
            between = "\n".join(lines[k] for k in range(prev_idx + 1, idx)).strip()
            if len(between) > 50:
                break
            run.append(idx)
            j += 1

        if len(run) >= 5:
            nav_lines.update(run)
            i = j
        else:
            i += 1

    if not nav_lines:
        return content

    return "\n".join(line for i, line in enumerate(lines) if i not in nav_lines)


# Patterns that indicate a page was blocked by bot protection (Cloudflare,
# hCaptcha, reCAPTCHA, etc.).  When all crawled pages match these patterns
# the content is useless; filtering them lets fallback tiers take over.
_BLOCKED_MARKERS = (
    "performing security verification",
    "sicherheitsüberprüfung",  # German CF
    "przeprowadzanie weryfikacji",  # Polish CF
    "biztonsági ellenőrzés",  # Hungarian CF
    "beveiliging wordt geverifieerd",  # Dutch CF
    "vérification de sécurité",  # French CF
    "verificación de seguridad",  # Spanish CF
    "verifica di sicurezza",  # Italian CF
    "enable javascript and cookies to continue",
    "just a moment...",  # legacy CF interstitial
    "challenges.cloudflare.com",
    "cf-chl-widget",
    "_cf_chl_opt",
    "turnstile",  # CF Turnstile widget
    "hcaptcha.com",
    "g-recaptcha",
    "ray id:",  # CF Ray ID (alone is weak, combined with short content)
)


def _is_blocked_content(content: str) -> bool:
    """Detect Cloudflare / CAPTCHA challenge pages.

    Returns True when the crawled content appears to be a bot-protection
    interstitial rather than real documentation.
    """
    if not content:
        return False
    lower = content.lower()
    # Count how many blocked markers appear
    hits = sum(1 for marker in _BLOCKED_MARKERS if marker in lower)
    # A single "Ray ID" in a long page isn't enough; require 2+ markers
    # or a single strong marker in a short page (< 2000 chars).
    if hits >= 2:
        return True
    if hits == 1 and len(content) < 2000:
        return True
    return False


def _clean_doc_content(content: str) -> str:
    """Strip noise from crawled documentation content.

    Removes badges, YAML frontmatter, mkdocs directives, mkdocstrings,
    HTML tags, TOC anchor links, navigation elements, footer boilerplate,
    navigation sidebar blocks, and navigation heading blocks.
    Applied before chunking to reduce index noise.
    """
    # Remove YAML frontmatter (must be at start of content)
    content = _FRONTMATTER_RE.sub("", content)

    # Remove badge images
    content = _BADGE_RE.sub("", content)

    # Remove mkdocs admonition blocks (keep content readable)
    content = _ADMONITION_RE.sub("", content)

    # Remove mkdocstrings directives
    content = _MKDOCSTRINGS_RE.sub("", content)

    # Remove standalone HTML tags (not code/pre)
    content = _HTML_TAG_RE.sub("", content)

    # Remove TOC anchor links (- [Title](#section))
    content = _TOC_LINK_RE.sub("", content)

    # Remove navigation sidebar blocks (MkDocs Material, Sphinx, etc.)
    content = _strip_nav_blocks(content)

    # Remove navigation heading blocks (## Topic A / ## Topic B / ...)
    content = _strip_nav_heading_blocks(content)

    # Filter noise lines
    lines = content.splitlines()
    cleaned = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            cleaned.append(line)
            continue
        if _NAV_RE.match(stripped):
            continue
        if _FOOTER_RE.match(stripped):
            continue
        if _MKDOCS_UI_RE.match(stripped):
            continue
        cleaned.append(line)

    return "\n".join(cleaned)


# ---------------------------------------------------------------------------
# Content chunking — split docs into searchable chunks
# ---------------------------------------------------------------------------

# Heading pattern for markdown
_HEADING_RE = re.compile(r"^(#{1,4})\s+(.+)$", re.MULTILINE)
# Fenced code block pattern (opening/closing ```)
_CODE_FENCE_RE = re.compile(r"^```")


def chunk_markdown(
    content: str,
    url: str = "",
    max_chunk_size: int = 1500,
    min_chunk_size: int = 100,
) -> list[dict]:
    """Split markdown content into semantic chunks by headings.

    Splits on ## and ### headings, keeping heading hierarchy.
    Chunks that are too large are further split by paragraphs,
    but never inside fenced code blocks.
    """
    if not content or not content.strip():
        return []

    # Clean noise (badges, navigation, footer) before chunking
    content = _clean_doc_content(content)
    if not content.strip():
        return []

    chunks: list[dict] = []
    current_title = ""
    heading_path = ""
    current_lines: list[str] = []

    def _flush():
        nonlocal current_lines
        text = "\n".join(current_lines).strip()
        if len(text) >= min_chunk_size:
            # Split oversized chunks by double newline, preserving code blocks
            if len(text) > max_chunk_size:
                _split_preserving_code(
                    text,
                    chunks,
                    current_title,
                    heading_path,
                    url,
                    max_chunk_size,
                    min_chunk_size,
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


def _split_preserving_code(
    text: str,
    chunks: list[dict],
    title: str,
    heading_path: str,
    url: str,
    max_chunk_size: int,
    min_chunk_size: int,
) -> None:
    """Split oversized text by paragraphs without breaking code blocks.

    Groups lines into segments separated by blank lines, but treats
    fenced code blocks (``` ... ```) as atomic units that are never split.
    """
    lines = text.split("\n")
    segments: list[str] = []
    current_segment: list[str] = []
    in_code_block = False

    for line in lines:
        if _CODE_FENCE_RE.match(line.strip()):
            in_code_block = not in_code_block

        if not in_code_block and line.strip() == "" and current_segment:
            # Paragraph boundary — flush segment
            segments.append("\n".join(current_segment))
            current_segment = []
        else:
            current_segment.append(line)

    if current_segment:
        segments.append("\n".join(current_segment))

    # Merge segments into chunks respecting max_chunk_size
    buffer = ""
    for seg in segments:
        if buffer and len(buffer) + len(seg) + 2 > max_chunk_size:
            if buffer.strip() and len(buffer.strip()) >= min_chunk_size:
                chunks.append(
                    {
                        "content": buffer.strip(),
                        "title": title,
                        "heading_path": heading_path,
                        "url": url,
                        "chunk_index": len(chunks),
                    }
                )
            buffer = seg
        else:
            buffer = f"{buffer}\n\n{seg}" if buffer else seg

    if buffer.strip() and len(buffer.strip()) >= min_chunk_size:
        chunks.append(
            {
                "content": buffer.strip(),
                "title": title,
                "heading_path": heading_path,
                "url": url,
                "chunk_index": len(chunks),
            }
        )


def chunk_llms_txt(content: str, base_url: str = "") -> list[dict]:
    """Chunk llms.txt / llms-full.txt content.

    llms.txt format uses markdown with clear section headers.
    """
    return chunk_markdown(content, url=base_url, max_chunk_size=2000)


# ---------------------------------------------------------------------------
# RST to Markdown (basic conversion for GitHub raw docs)
# ---------------------------------------------------------------------------

# RST heading underline characters (in decreasing priority)
_RST_HEADING_CHARS = set("=-~^\"'+`:._;,#*!?/\\|")

# RST directive pattern: .. directive:: args
_RST_DIRECTIVE_RE = re.compile(r"^\.\.\s+(\w[\w-]*)::(.*)$")
# RST role pattern: :role:`text`
_RST_ROLE_RE = re.compile(r":(\w+):`([^`]*)`")
# RST substitution: |text|
_RST_SUBST_RE = re.compile(r"\|(\w[\w\s]*)\|")


def _rst_to_markdown(content: str) -> str:
    """Convert RST content to rough Markdown for indexing.

    Not a full parser — handles the most common patterns:
    - Headings (underlined titles)
    - Code blocks (``.. code-block::``, ``.. code::``, literal blocks)
    - Cross-references (`:ref:`, `:doc:`, `:class:`, etc.)
    - Directives (stripped except code blocks)
    - Bold/italic/code inline markup
    """
    if not content:
        return ""

    lines = content.split("\n")
    out: list[str] = []
    i = 0
    in_code_block = False
    code_indent = 0

    while i < len(lines):
        line = lines[i]

        # Handle literal blocks (indented after ::)
        if in_code_block:
            stripped = line.strip()
            if stripped and not line.startswith(" " * code_indent) and not line == "":
                # End of indented block
                in_code_block = False
                out.append("```")
                out.append("")
                # Don't increment — reprocess this line
                continue
            out.append(line)
            i += 1
            continue

        # Detect RST headings: line followed by underline of same length
        if (
            i + 1 < len(lines)
            and line.strip()
            and len(lines[i + 1].strip()) >= len(line.strip())
            and lines[i + 1].strip()
            and all(c in _RST_HEADING_CHARS for c in lines[i + 1].strip())
            and len(set(lines[i + 1].strip())) == 1
        ):
            underline_char = lines[i + 1].strip()[0]
            # Also check for overline + title + underline
            if underline_char == "=":
                level = "#"
            elif underline_char == "-":
                level = "##"
            elif underline_char == "~":
                level = "###"
            else:
                level = "####"

            # Check if there's an overline (line before is same underline char)
            if (
                i > 0
                and out
                and out[-1].strip()
                and all(c in _RST_HEADING_CHARS for c in out[-1].strip())
                and len(set(out[-1].strip())) == 1
            ):
                out[-1] = ""  # Remove overline

            out.append(f"{level} {line.strip()}")
            i += 2  # Skip underline
            continue

        # Detect code-block directive
        directive_match = _RST_DIRECTIVE_RE.match(line.strip())
        if directive_match:
            directive = directive_match.group(1).lower()
            args = directive_match.group(2).strip()
            if directive in ("code-block", "code", "sourcecode", "highlight"):
                lang = args or ""
                out.append(f"```{lang}")
                # Skip any directive options (indented lines starting with :)
                i += 1
                while i < len(lines) and (
                    not lines[i].strip() or lines[i].strip().startswith(":")
                ):
                    i += 1
                # Remaining indented lines are the code
                if i < len(lines):
                    code_indent = len(lines[i]) - len(lines[i].lstrip())
                    if code_indent < 2:
                        code_indent = 3
                in_code_block = True
                continue
            elif directive in (
                "literalinclude",
                "image",
                "figure",
                "raw",
                "include",
                "toctree",
                "contents",
                "moduleauthor",
                "sectionauthor",
                "meta",
                "deprecated",
            ):
                # Skip these directives entirely
                i += 1
                while i < len(lines) and (
                    not lines[i].strip() or lines[i].startswith("   ")
                ):
                    i += 1
                continue
            elif directive in ("note", "warning", "tip", "important", "seealso"):
                out.append(f"> **{directive.title()}:** {args}")
                i += 1
                # Include indented body
                while i < len(lines) and (
                    not lines[i].strip() or lines[i].startswith("   ")
                ):
                    body = lines[i].strip()
                    if body:
                        out.append(f"> {body}")
                    i += 1
                continue
            # Other directives: skip header, keep body
            i += 1
            while i < len(lines) and lines[i].strip().startswith(":"):
                i += 1  # Skip options
            continue

        # Detect literal block ending with ::
        if line.rstrip().endswith("::"):
            out.append(line.rstrip()[:-2] + ":" if len(line.rstrip()) > 2 else "")
            i += 1
            # Skip blank lines
            while i < len(lines) and not lines[i].strip():
                i += 1
            if i < len(lines):
                code_indent = len(lines[i]) - len(lines[i].lstrip())
                if code_indent < 2:
                    code_indent = 3
                out.append("```")
                in_code_block = True
            continue

        # Process inline RST markup
        processed = line
        # :role:`text` → `text`
        processed = _RST_ROLE_RE.sub(r"`\2`", processed)
        # ``code`` → `code`
        processed = processed.replace("``", "`")
        out.append(processed)
        i += 1

    if in_code_block:
        out.append("```")

    return "\n".join(out)


# ---------------------------------------------------------------------------
# GitHub raw markdown — fetch docs directly from repo
# ---------------------------------------------------------------------------

# Pattern to extract owner/repo from GitHub URLs
_GH_REPO_RE = re.compile(r"github\.com/([^/]+)/([^/]+?)(?:\.git)?(?:/|$)")

# Common docs directory names in repos
_DOC_DIRS = ("docs", "doc", "documentation", "guide", "guides", "wiki")

# Non-documentation files to skip (case-insensitive stem matching)
_SKIP_FILES = frozenset(
    {
        "changelog",
        "changes",
        "history",
        "contributing",
        "contributors",
        "code_of_conduct",
        "code-of-conduct",
        "license",
        "licence",
        "security",
        "release",
        "releases",
        "release-notes",
        "release_notes",
        "authors",
        "funding",
        "sponsors",
        "support",
        "codeowners",
        "pull_request_template",
        "issue_template",
        "bug_report",
        "feature_request",
    }
)

# ISO 639-1 language codes commonly used for i18n docs directories
_I18N_LANG_CODES = frozenset(
    {
        "af",
        "am",
        "ar",
        "az",
        "be",
        "bg",
        "bn",
        "bs",
        "ca",
        "cs",
        "cy",
        "da",
        "de",
        "el",
        "en",
        "eo",
        "es",
        "et",
        "eu",
        "fa",
        "fi",
        "fr",
        "ga",
        "gl",
        "gu",
        "ha",
        "he",
        "hi",
        "hr",
        "hu",
        "hy",
        "id",
        "is",
        "it",
        "ja",
        "ka",
        "kk",
        "km",
        "kn",
        "ko",
        "ku",
        "ky",
        "lo",
        "lt",
        "lv",
        "mk",
        "ml",
        "mn",
        "mr",
        "ms",
        "my",
        "nb",
        "ne",
        "nl",
        "nn",
        "no",
        "pa",
        "pl",
        "ps",
        "pt",
        "ro",
        "ru",
        "si",
        "sk",
        "sl",
        "sq",
        "sr",
        "sv",
        "sw",
        "ta",
        "te",
        "th",
        "tl",
        "tr",
        "uk",
        "ur",
        "uz",
        "vi",
        "zh",
        # Common regional variants
        "pt-br",
        "zh-cn",
        "zh-tw",
        "zh-hans",
        "zh-hant",
    }
)

# Template/macro pattern (Jinja2, mkdocs-macros, etc.)
_TEMPLATE_MACRO_RE = re.compile(r"\{\{.*?\}\}")

# Frameworks commonly used in monorepo docs with framework/* subdirectories
_KNOWN_FRAMEWORKS = frozenset(
    {"react", "angular", "vue", "svelte", "solid", "qwik", "lit", "preact"}
)


def _filter_framework_paths(paths: list[str], library_hint: str) -> list[str]:
    """Filter docs paths to matching framework variant in monorepo docs.

    Detects patterns like ``docs/framework/react/...`` vs
    ``docs/framework/angular/...`` and keeps only the one matching
    the library name (e.g., ``@tanstack/react-query`` -> keep ``react``).
    """
    framework_dir_re = re.compile(r"(?:^|/)framework/(\w+)/")
    framework_paths: dict[str, list[str]] = {}
    non_framework_paths: list[str] = []

    for p in paths:
        match = framework_dir_re.search(p.lower())
        if match and match.group(1) in _KNOWN_FRAMEWORKS:
            fw = match.group(1)
            framework_paths.setdefault(fw, []).append(p)
        else:
            non_framework_paths.append(p)

    if len(framework_paths) < 2:
        return paths

    # Extract framework hint from library name
    # e.g., "@tanstack/react-query" -> "react", "vue-router" -> "vue"
    hint_parts = library_hint.lower().replace("@", "").replace("/", "-").split("-")
    matching_fw = None
    for part in hint_parts:
        if part in framework_paths:
            matching_fw = part
            break

    if matching_fw:
        logger.info(
            f"Framework filter: keeping '{matching_fw}' docs "
            f"({len(framework_paths[matching_fw])} files), "
            f"skipping {', '.join(f for f in framework_paths if f != matching_fw)}"
        )
        return non_framework_paths + framework_paths[matching_fw]

    return paths


def _filter_doc_paths(
    md_paths: list[str], library_hint: str = ""
) -> tuple[list[str], bool]:
    """Smart filtering of markdown file paths from a GitHub repository tree.

    Handles three key problems:
    1. i18n directories — only keeps English or language-neutral docs
    2. Deeply nested docs — prefers top-level docs/ over packages/*/docs/
    3. README deprioritization — moves README.md to end of list

    Args:
        md_paths: List of file paths from GitHub tree API.

    Returns:
        Tuple of (filtered paths, has_primary_docs). ``has_primary_docs`` is
        True when the repo has a top-level ``docs/`` or similar directory,
        indicating the raw markdown is likely user-facing documentation
        rather than internal/tooling docs.
    """
    if not md_paths:
        return [], False

    # Separate README from docs
    readme_paths: list[str] = []
    doc_paths: list[str] = []
    for p in md_paths:
        if p.rsplit("/", 1)[-1].lower() in (
            "readme.md",
            "readme.mdx",
            "readme.rst",
        ):
            readme_paths.append(p)
        else:
            doc_paths.append(p)

    # --- Step 1: Detect and filter i18n structure ---
    # Look for sibling directories that are ISO 639-1 codes
    # e.g. docs/en/, docs/de/, docs/ja/ → keep only docs/en/
    i18n_filtered = _filter_i18n_paths(doc_paths)

    # --- Step 2: Prioritize top-level docs over deeply nested ---
    primary: list[str] = []  # docs/file.md, doc/guide/file.md
    nested: list[str] = []  # packages/foo/docs/file.md

    for p in i18n_filtered:
        parts = p.split("/")
        # Check if the FIRST segment is a doc directory
        if parts and parts[0].lower() in _DOC_DIRS:
            primary.append(p)
        else:
            nested.append(p)

    has_primary = len(primary) >= 5

    # Use nested docs only if primary docs has <5 files
    if has_primary:
        result = primary
    else:
        result = primary + nested

    # --- Step 3: Append README(s) at end (lowest priority) ---
    # Only include root README, not every sub-package README
    root_readmes = [p for p in readme_paths if "/" not in p]
    result.extend(root_readmes)

    # --- Step 4: Framework-specific filtering ---
    if library_hint:
        result = _filter_framework_paths(result, library_hint)

    return result, has_primary


def _filter_i18n_paths(paths: list[str]) -> list[str]:
    """Filter out non-English i18n documentation paths.

    Detects i18n structure by finding sibling directories under a common
    parent that match ISO 639-1 language codes. When i18n is detected,
    keeps only English (``en``) paths and language-neutral paths.

    Handles common patterns:
    - ``docs/en/...``, ``docs/de/...`` (direct lang subdirs)
    - ``docs/i18n/en/...``, ``docs/i18n/de/...`` (i18n subdir)
    - ``i18n/en/...``, ``i18n/de/...`` (top-level i18n)
    """
    if not paths:
        return paths

    # Group paths by their first two segments to detect i18n siblings
    # e.g. "docs/de/tutorial.md" → parent="docs", child_dir="de"
    parent_children: dict[str, set[str]] = {}
    for p in paths:
        parts = p.split("/")
        if len(parts) >= 3:
            parent = parts[0]
            child = parts[1].lower()
            parent_children.setdefault(parent, set()).add(child)

    # Find parents that have ≥2 children matching language codes
    i18n_parents: set[str] = set()
    for parent, children in parent_children.items():
        lang_codes = children & _I18N_LANG_CODES
        if len(lang_codes) >= 2:
            i18n_parents.add(parent)

    if not i18n_parents:
        return paths

    # Filter: for i18n parents, only keep English or language-neutral paths
    filtered: list[str] = []
    for p in paths:
        parts = p.split("/")
        if len(parts) >= 3 and parts[0] in i18n_parents:
            child = parts[1].lower()
            if child in _I18N_LANG_CODES:
                # Language directory — only keep English
                if child == "en":
                    filtered.append(p)
                # else: skip non-English translation
            else:
                # Not a language dir (e.g. docs/api/, docs/guide/) — keep
                filtered.append(p)
        else:
            # Path not under an i18n parent — keep
            filtered.append(p)

    logger.info(
        f"i18n filter: {len(paths)} paths → {len(filtered)} "
        f"(skipped translations under: {', '.join(sorted(i18n_parents))})"
    )
    return filtered


def _has_excessive_macros(content: str, threshold: float = 0.15) -> bool:
    """Check if content has too many template macros to be useful.

    Returns True if >15% of non-empty lines contain ``{{...}}`` patterns,
    indicating unrendered Jinja2/mkdocs-macros content.
    """
    lines = [ln for ln in content.splitlines() if ln.strip()]
    if len(lines) < 5:
        return False
    macro_lines = sum(1 for ln in lines if _TEMPLATE_MACRO_RE.search(ln))
    return macro_lines / len(lines) > threshold


def _strip_template_macros(content: str) -> str:
    """Strip lines containing unrendered template macros.

    Removes lines with ``{{...}}`` patterns (Jinja2/mkdocs-macros) that
    produce noise in raw markdown. Keeps the rest of the content intact.
    """
    lines = content.splitlines()
    cleaned = [ln for ln in lines if not _TEMPLATE_MACRO_RE.search(ln)]
    return "\n".join(cleaned)


# Regex matching a URL path segment that is a language code (non-English)
# Matches: /ja/, /de/, /zh-cn/, /pt-br/, /zh-hans/
# Does NOT match: /en/, /api/, /docs/, /v2/
_I18N_URL_SEGMENT_RE = re.compile(
    r"/(?!en(?:[/-]|$))"  # Not English
    r"("
    + "|".join(
        re.escape(str(code))
        for code in sorted(_I18N_LANG_CODES, key=len, reverse=True)
        if code != "en"
    )
    + r")(?=/|$)",
    re.IGNORECASE,
)


def _is_i18n_url(path: str, root_path: str) -> bool:
    """Check if a URL path is a translated (non-English) page.

    Compares the link path against the root docs path to detect language
    code segments that appear in the link but not in the root.
    This avoids false positives when ``en`` appears in the root path.

    Examples::

        _is_i18n_url("/ja/6.0/tutorial/", "/en/6.0/")  -> True
        _is_i18n_url("/en/6.0/tutorial/", "/en/6.0/")  -> False
        _is_i18n_url("/docs/tutorial/",   "/docs/")     -> False
        _is_i18n_url("/de/docs/models/",  "/")          -> True
    """
    # Only flag as i18n if the lang segment is NOT in the root path
    match = _I18N_URL_SEGMENT_RE.search(path)
    if not match:
        return False

    lang_segment = match.group(1).lower()
    # If the root path also has this segment, it's not a translation branch
    # (e.g. the site IS the German version)
    return f"/{lang_segment}/" not in root_path.lower()


async def _fetch_github_readme(repo_url: str) -> list[dict] | None:
    """Fetch just the README.md from a GitHub repository.

    Last-resort fallback when all other tiers fail.  Returns chunked
    README content so at least *some* documentation is available.
    """
    match = _GH_REPO_RE.search(repo_url)
    if not match:
        return None

    owner, repo = match.group(1), match.group(2)

    async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
        # Try common README filenames on HEAD (avoids an API call to
        # resolve default branch).
        for fname in (
            "README.md",
            "README.rst",
            "readme.md",
            "README.markdown",
            "Readme.md",
        ):
            raw_url = f"https://raw.githubusercontent.com/{owner}/{repo}/HEAD/{fname}"
            try:
                resp = await client.get(raw_url)
                if resp.status_code != 200 or len(resp.text) < 50:
                    continue
                content = resp.text
                if fname.lower().endswith(".rst"):
                    content = _rst_to_markdown(content)

                gh_page_url = f"https://github.com/{owner}/{repo}"
                chunks = chunk_markdown(content=content, url=gh_page_url)
                if chunks:
                    return chunks
            except Exception:
                continue
    return None


async def _try_github_raw_docs(
    repo_url: str,
    max_files: int = 50,
    library_hint: str = "",
) -> list[dict] | None:
    """Fetch raw markdown docs from a GitHub repository.

    Uses GitHub API to list docs directories and fetch raw ``.md`` files.
    Produces cleaner content than crawling rendered HTML pages.

    Smart filtering:
    - Skips non-English translations (i18n detection)
    - Prefers top-level ``docs/`` over deeply nested doc directories
    - Deprioritizes README.md (appended last)
    - Skips files with excessive template macros (unrendered Jinja2)

    Args:
        repo_url: URL containing ``github.com/owner/repo``
        max_files: Maximum number of markdown files to fetch

    Returns:
        List of ``{url, title, content}`` dicts if successful, ``None`` otherwise.
    """
    match = _GH_REPO_RE.search(repo_url)
    if not match:
        return None

    owner, repo = match.group(1), match.group(2)
    api_base = f"https://api.github.com/repos/{owner}/{repo}"
    raw_base = f"https://raw.githubusercontent.com/{owner}/{repo}"

    async with httpx.AsyncClient(timeout=20) as client:
        # Resolve default branch
        try:
            resp = await client.get(
                api_base,
                headers={
                    "Accept": "application/vnd.github.v3+json",
                    **_github_headers(),
                },
            )
            if resp.status_code != 200:
                return None
            default_branch = resp.json().get("default_branch", "main")
        except Exception:
            return None

        # Collect all candidate markdown files from tree API
        candidate_paths: list[str] = []
        try:
            resp = await client.get(
                f"{api_base}/git/trees/{default_branch}?recursive=1",
                headers={
                    "Accept": "application/vnd.github.v3+json",
                    **_github_headers(),
                },
            )
            if resp.status_code != 200:
                return None

            tree = resp.json().get("tree", [])
            for item in tree:
                if item.get("type") != "blob":
                    continue
                path = item.get("path", "")
                path_lower = path.lower()

                # Skip .github/ directory files (templates, workflows)
                if path_lower.startswith(".github/"):
                    continue

                # Skip known non-doc files by stem
                fname = path.rsplit("/", 1)[-1]
                stem = fname.rsplit(".", 1)[0].lower()
                if stem in _SKIP_FILES:
                    continue

                # Include root README.md
                if path_lower == "readme.md" or path_lower == "readme.rst":
                    candidate_paths.append(path)
                    continue

                # Only markdown and RST files
                if not path_lower.endswith((".md", ".mdx", ".rst")):
                    continue

                # Must be in a docs-like directory
                parts = path.split("/")
                if any(p.lower() in _DOC_DIRS for p in parts):
                    candidate_paths.append(path)
        except Exception:
            return None

        if not candidate_paths:
            return None

        # Apply smart filtering (i18n, depth priority, README last, framework)
        filtered_paths, has_primary = _filter_doc_paths(
            candidate_paths, library_hint=library_hint
        )

        if not filtered_paths:
            return None

        # If no top-level docs/ directory found, the repo likely keeps
        # user-facing docs on a separate site (e.g. react.dev, angular.dev).
        # Skip GitHub raw fallback so Tier 2 (crawl docs site) is used.
        if not has_primary:
            logger.info(
                f"Skipping GitHub raw docs for {owner}/{repo}: "
                "no top-level docs directory found (only nested/internal docs)"
            )
            return None

        # Fetch raw content for each markdown file
        pages: list[dict] = []
        skipped_macros = 0
        fetch_original_bytes = 0
        fetch_stripped_bytes = 0
        for fpath in filtered_paths[:max_files]:
            raw_url = f"{raw_base}/{default_branch}/{fpath}"
            try:
                resp = await client.get(raw_url)
                if resp.status_code != 200:
                    continue
                content = resp.text
                if len(content) < 50:
                    continue

                # Skip files with excessive template macros;
                # strip scattered macros from otherwise useful files
                if _has_excessive_macros(content):
                    skipped_macros += 1
                    continue

                original_len = len(content)
                content = _strip_template_macros(content)
                fetch_original_bytes += original_len
                fetch_stripped_bytes += len(content)

                # Convert RST to Markdown for consistent chunking
                if fpath.lower().endswith(".rst"):
                    content = _rst_to_markdown(content)

                # Derive title from filename
                fname = fpath.rsplit("/", 1)[-1]
                title = fname.rsplit(".", 1)[0].replace("-", " ").replace("_", " ")

                gh_page_url = (
                    f"https://github.com/{owner}/{repo}/blob/{default_branch}/{fpath}"
                )
                pages.append(
                    {
                        "url": gh_page_url,
                        "title": title,
                        "content": content,
                    }
                )
            except Exception:
                continue

        if skipped_macros:
            logger.info(
                f"Skipped {skipped_macros} files with excessive template macros"
            )

        # Quality gate: if the repo uses heavy templating (many files skipped
        # or significant content lost to macro stripping), fall through to
        # Tier 2 crawl where the docs build system renders macros properly.
        total_files = skipped_macros + len(pages)
        if total_files >= 5 and skipped_macros > 0:
            skip_ratio = skipped_macros / total_files
            content_loss = (
                1 - fetch_stripped_bytes / fetch_original_bytes
                if fetch_original_bytes > 0
                else 0
            )
            if skip_ratio > 0.25 or content_loss > 0.10:
                logger.info(
                    f"Heavy templating in {owner}/{repo}: "
                    f"{skipped_macros}/{total_files} files skipped, "
                    f"{content_loss:.0%} content lost to macros. "
                    "Falling through to crawl"
                )
                return None

        if pages:
            logger.info(
                f"Fetched {len(pages)} raw markdown docs from github.com/{owner}/{repo}"
            )
            return pages

    return None


# ---------------------------------------------------------------------------
# Sitemap discovery — find all docs URLs from sitemap.xml
# ---------------------------------------------------------------------------


async def _try_sitemap(base_url: str, max_urls: int = 50) -> list[str]:
    """Try fetching sitemap.xml and extracting docs page URLs.

    Helps discover pages on SPA sites where link extraction from
    rendered HTML yields only the JS shell page.
    """
    parsed = urlparse(base_url)
    origin = f"{parsed.scheme}://{parsed.netloc}"

    for path in ("/sitemap.xml", "/sitemap_index.xml"):
        url = f"{origin}{path}"
        try:
            async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
                resp = await client.get(url)
                if resp.status_code != 200:
                    continue
                text = resp.text
                if "<urlset" not in text and "<sitemapindex" not in text:
                    continue

                # Handle sitemap index (links to sub-sitemaps)
                if "<sitemapindex" in text:
                    sub_urls = re.findall(r"<loc>\s*(.*?)\s*</loc>", text)
                    all_page_urls: list[str] = []
                    for sub_url in sub_urls[:5]:
                        try:
                            sub_resp = await client.get(sub_url)
                            if sub_resp.status_code == 200:
                                sub_locs = re.findall(
                                    r"<loc>\s*(.*?)\s*</loc>", sub_resp.text
                                )
                                all_page_urls.extend(sub_locs)
                        except Exception:
                            continue
                    urls = all_page_urls
                else:
                    urls = re.findall(r"<loc>\s*(.*?)\s*</loc>", text)

                # Filter to same domain, skip non-doc paths
                skip_patterns = (
                    "/blog/",
                    "/changelog",
                    "/releases",
                    "/feed",
                    "/rss",
                    "/sitemap",
                    "/robots.txt",
                    "/search",
                    "/genindex",
                    "/searchindex",
                    "/modindex",
                    "/_modules/",
                    "/_sources/",
                )
                filtered = [
                    u
                    for u in urls
                    if parsed.netloc in u
                    and not any(skip in u.lower() for skip in skip_patterns)
                ]

                if filtered:
                    logger.info(f"Found {len(filtered)} URLs from sitemap at {url}")
                    return filtered[:max_urls]
        except Exception:
            continue

    return []


async def _try_objects_inv(base_url: str, max_urls: int = 50) -> list[str]:
    """Try fetching Sphinx ``objects.inv`` to discover doc page URLs.

    Sphinx-based sites (ReadTheDocs, Pallets, etc.) publish an
    ``objects.inv`` file listing every documented object and its URL.
    This is far more reliable than sitemap.xml for Sphinx sites, which
    often serve a minimal root sitemap with only version-level entries.

    Tries multiple candidate paths to handle cases like boto3 where the
    docs URL is ``/api/`` but objects.inv lives at ``/api/latest/``.
    """
    # Resolve the actual base URL (handle redirects like / -> /en/latest/)
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            resp = await client.get(base_url)
            actual_url = str(resp.url).rstrip("/") + "/"
    except Exception:
        actual_url = base_url.rstrip("/") + "/"

    # Build candidate URLs for objects.inv:
    # 1. At the resolved URL (most common: /en/latest/objects.inv)
    # 2. At /latest/ subdirectory (boto3: /api/latest/objects.inv)
    # 3. At /stable/ subdirectory (some projects use stable by default)
    candidates = [
        f"{actual_url}objects.inv",
        f"{actual_url}latest/objects.inv",
        f"{actual_url}stable/objects.inv",
    ]
    # Deduplicate while preserving order
    seen: set[str] = set()
    unique_candidates = []
    for c in candidates:
        if c not in seen:
            seen.add(c)
            unique_candidates.append(c)

    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            for inv_url in unique_candidates:
                try:
                    resp = await client.get(inv_url)
                except Exception:
                    continue
                if resp.status_code != 200:
                    continue
                data = resp.content
                if not data.startswith(b"# Sphinx inventory version"):
                    continue

                # Determine the base URL for constructing page URLs:
                # objects.inv path minus "objects.inv" = doc root
                inv_base = inv_url.rsplit("objects.inv", 1)[0]

                result = _parse_objects_inv(data, inv_base)
                if result:
                    logger.info(
                        f"Found {len(result)} URLs from objects.inv at {inv_url}"
                    )
                    return result[:max_urls]
    except Exception:
        pass

    return []


def _parse_objects_inv(data: bytes, base_url: str) -> list[str]:
    """Parse Sphinx objects.inv binary data and extract doc page URLs.

    The binary format is:
    - 4 header lines (text)
    - Remaining bytes: zlib-compressed entries
    - Each entry: ``name domain:type priority uri displayname``
    """
    # Find header end (4 newlines)
    header_end = 0
    newline_count = 0
    for i, b in enumerate(data):
        if b == ord("\n"):
            newline_count += 1
            if newline_count == 4:
                header_end = i + 1
                break

    # Decompress rest
    compressed = data[header_end:]
    try:
        decompressed = zlib.decompress(compressed)
        text = decompressed.decode("utf-8", errors="replace")
    except Exception:
        return []

    # Parse entries — only std:doc (pages) and std:label (sections)
    doc_urls: set[str] = set()
    for line in text.splitlines():
        if not line.strip():
            continue
        parts = line.split(" ", 4)
        if len(parts) < 4:
            continue
        name = parts[0]
        domain_type = parts[1]
        uri = parts[3]

        if domain_type not in ("std:doc", "std:label"):
            continue
        if uri.endswith("$"):
            uri = name
        # Remove fragment, keep path only
        uri = uri.split("#")[0]
        if not uri or uri.startswith("http"):
            continue
        # Skip non-doc paths
        uri_lower = uri.lower()
        if any(
            skip in uri_lower
            for skip in (
                "changelog",
                "changes",
                "genindex",
                "modindex",
                "searchindex",
                "_modules/",
                "_sources/",
            )
        ):
            continue
        doc_urls.add(f"{base_url}{uri}")

    return sorted(doc_urls)

    return []


# ---------------------------------------------------------------------------
# Docs fetching with Crawl4AI
# ---------------------------------------------------------------------------


async def fetch_docs_pages(
    docs_url: str,
    query: str = "",
    max_pages: int = 50,
    batch_timeout: int = 45,
) -> list[dict]:
    """Fetch documentation pages from a docs site with depth-2 crawling.

    Strategy:
    1. Fetch the root docs page, extract internal links
    2. Discover more URLs from sitemap.xml
    3. Fetch first batch of pages (round 1)
    4. Extract links from round-1 results (depth-2 discovery)
    5. Fetch second batch from newly discovered URLs (round 2)

    Args:
        batch_timeout: Per-batch crawl timeout in seconds. Each round
            (root, round1, round2) is bounded by this limit.

    Returns list of {url, title, content} dicts.
    """
    from wet_mcp.sources.crawler import extract

    # SPA-friendly crawl settings: scroll full page to trigger lazy-loaded
    # content and add a small delay for JS rendering before capture.
    _SPA_KWARGS: dict = {
        "scan_full_page": True,
        "delay_before_return_html": 1.0,
    }

    # Step 1: Fetch root page
    logger.info(f"Fetching docs root: {docs_url}")
    try:
        root_result_str = await asyncio.wait_for(
            extract(urls=[docs_url], format="markdown", stealth=True, **_SPA_KWARGS),
            timeout=batch_timeout,
        )
    except TimeoutError:
        logger.warning(f"Root page fetch timed out after {batch_timeout}s: {docs_url}")
        return []
    root_results = json.loads(root_result_str)

    pages: list[dict] = []
    seen_urls: set[str] = {docs_url}
    pending_urls: list[str] = []

    # For GitHub URLs, restrict crawl to the same repo path
    docs_parsed = urlparse(docs_url)
    _is_github = "github.com" in docs_parsed.netloc
    _gh_path_prefix = "/".join(docs_parsed.path.strip("/").split("/")[:2])
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

    # Generated/index pages to skip (Sphinx, MkDocs, etc.)
    _skip_url_patterns = (
        "/genindex",
        "/searchindex",
        "/modindex",
        "/_modules/",
        "/_sources/",
        "/blog/",
        "/changelog",
        "/releases",
    )

    # Detect redirect: if actual URL differs from docs_url (e.g., versioned
    # docs), use the redirected path as prefix to restrict crawling to that
    # version.  Prevents crawling sibling version pages (/en/13/, /en/14/).
    _version_prefix = ""
    for r in root_results:
        actual_url = r.get("url", "")
        if actual_url and actual_url != docs_url:
            actual_parsed = urlparse(actual_url)
            if actual_parsed.netloc == docs_parsed.netloc:
                actual_path = actual_parsed.path.rstrip("/")
                actual_parts = [s for s in actual_path.split("/") if s]
                if len(actual_parts) >= 2:
                    _version_prefix = "/" + "/".join(actual_parts) + "/"
                    seen_urls.add(actual_url)
                    logger.info(f"Detected version prefix: {_version_prefix}")
            break

    def _collect_links(result: dict) -> list[str]:
        """Extract valid doc URLs from a crawl result."""
        urls: list[str] = []
        internal = result.get("links", {}).get("internal", [])
        for link in internal:
            href = link.get("href", "") if isinstance(link, dict) else link
            if not href:
                continue
            parsed = urlparse(href)
            if parsed.netloc and parsed.netloc != docs_parsed.netloc:
                continue
            full_url = urljoin(docs_url, href)
            if full_url in seen_urls:
                continue
            full_parsed = urlparse(full_url)

            # Skip generated index/module pages
            if any(pat in full_parsed.path.lower() for pat in _skip_url_patterns):
                continue

            # GitHub-specific: stay within same repo
            if _is_github:
                path_parts = full_parsed.path.strip("/").split("/")
                if path_parts and path_parts[0] in _gh_skip_paths:
                    continue
                if "/".join(path_parts[:2]) != _gh_path_prefix:
                    continue

            # Skip translated (non-English) pages
            if _is_i18n_url(full_parsed.path, docs_parsed.path):
                continue

            # Versioned docs: restrict to same version path prefix
            if _version_prefix and not full_parsed.path.startswith(_version_prefix):
                continue

            urls.append(full_url)
            seen_urls.add(full_url)
        return urls

    def _sort_by_query(urls: list[str]) -> list[str]:
        """Sort URLs by query term overlap (highest first)."""
        if not query or not urls:
            return urls
        query_words = set(query.lower().split())
        scored = []
        for url in urls:
            path_words = set(re.split(r"[-_/.]", urlparse(url).path.lower()))
            overlap = len(query_words & path_words)
            scored.append((url, overlap))
        scored.sort(key=lambda x: x[1], reverse=True)
        return [u for u, _ in scored]

    # Process root page results
    blocked_count = 0
    for r in root_results:
        if r.get("content") and not r.get("error"):
            if _is_blocked_content(r["content"]):
                blocked_count += 1
                continue
            pages.append(
                {
                    "url": r["url"],
                    "title": r.get("title", ""),
                    "content": r["content"],
                }
            )
            pending_urls.extend(_collect_links(r))

    # Early exit: if root page was blocked, all other pages on the same
    # domain will also be blocked — skip expensive crawling and return
    # empty so that upstream fallback (GitHub raw, SearXNG) can take over.
    if blocked_count > 0 and not pages:
        logger.warning(
            f"Root page blocked by bot protection, skipping crawl: {docs_url}"
        )
        return pages

    # Sitemap + objects.inv discovery (finds URLs not linked from root page)
    # Run both in parallel — objects.inv is more reliable for Sphinx sites,
    # sitemap.xml works for non-Sphinx sites
    # Bounded by batch_timeout to prevent hanging on slow servers
    sitemap_task = _try_sitemap(docs_url, max_urls=max_pages)
    inv_task = _try_objects_inv(docs_url, max_urls=max_pages)
    try:
        sitemap_urls, inv_urls = await asyncio.wait_for(
            asyncio.gather(sitemap_task, inv_task),
            timeout=batch_timeout,
        )
    except TimeoutError:
        logger.warning(
            f"Sitemap/objects.inv discovery timed out after {batch_timeout}s"
        )
        sitemap_urls, inv_urls = [], []

    # Merge: objects.inv URLs first (more reliable for Sphinx), then sitemap
    inv_url_set = set(inv_urls)
    extra_urls = list(inv_urls) + [u for u in sitemap_urls if u not in inv_url_set]
    for su in extra_urls:
        su_parsed = urlparse(su)
        if su in seen_urls:
            continue
        if _is_i18n_url(su_parsed.path, docs_parsed.path):
            continue
        # objects.inv URLs already include the correct version path from
        # redirect resolution; only apply version prefix filter to sitemap URLs
        if su not in inv_url_set:
            if _version_prefix and not su_parsed.path.startswith(_version_prefix):
                continue
        pending_urls.append(su)
        seen_urls.add(su)

    # Sort by query relevance
    pending_urls = _sort_by_query(pending_urls)

    # --- Fetch round 1 ---
    remaining = max_pages - len(pages)
    if remaining > 0 and pending_urls:
        # Reserve some capacity for depth-2 round
        round1_limit = min(len(pending_urls), remaining * 2 // 3 or remaining)
        batch1_urls = pending_urls[:round1_limit]
        pending_urls = pending_urls[round1_limit:]

        logger.info(f"Fetching {len(batch1_urls)} docs pages (round 1)...")
        try:
            batch1_str = await asyncio.wait_for(
                extract(
                    urls=batch1_urls, format="markdown", stealth=True, **_SPA_KWARGS
                ),
                timeout=batch_timeout,
            )
            batch1_results = json.loads(batch1_str)

            for br in batch1_results:
                if br.get("content") and not br.get("error"):
                    if _is_blocked_content(br["content"]):
                        blocked_count += 1
                        continue
                    pages.append(
                        {
                            "url": br["url"],
                            "title": br.get("title", ""),
                            "content": br["content"],
                        }
                    )
                    # Depth-2: discover links from fetched pages
                    pending_urls.extend(_collect_links(br))
        except TimeoutError:
            logger.warning(
                f"Round 1 crawl timed out after {batch_timeout}s "
                f"({len(batch1_urls)} pages)"
            )

    # --- Fetch round 2 (depth-2 discovery) ---
    remaining = max_pages - len(pages)
    if remaining > 0 and pending_urls:
        pending_urls = _sort_by_query(pending_urls)
        batch2_urls = pending_urls[:remaining]
        if batch2_urls:
            logger.info(f"Fetching {len(batch2_urls)} docs pages (round 2, depth-2)...")
            try:
                batch2_str = await asyncio.wait_for(
                    extract(
                        urls=batch2_urls, format="markdown", stealth=True, **_SPA_KWARGS
                    ),
                    timeout=batch_timeout,
                )
                batch2_results = json.loads(batch2_str)
                for br in batch2_results:
                    if br.get("content") and not br.get("error"):
                        if _is_blocked_content(br["content"]):
                            blocked_count += 1
                            continue
                        pages.append(
                            {
                                "url": br["url"],
                                "title": br.get("title", ""),
                                "content": br["content"],
                            }
                        )
            except TimeoutError:
                logger.warning(
                    f"Round 2 crawl timed out after {batch_timeout}s "
                    f"({len(batch2_urls)} pages)"
                )

    if blocked_count:
        logger.warning(f"Filtered {blocked_count} bot-protected pages from {docs_url}")
    logger.info(f"Fetched {len(pages)} docs pages from {docs_url}")
    return pages
