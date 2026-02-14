"""Benchmark test suite for docs search quality (50 libraries).

Run manually or via CI to validate docs search quality after changes.
Each test case specifies a library, query, and expected quality signals.

Usage:
    uv run pytest tests/benchmark_docs_search.py -v --timeout=120 -k "test_docs_benchmark"

NOTE: These are live integration tests that hit external APIs.
      Mark with @pytest.mark.benchmark to skip in regular CI.
"""

# fmt: off
# ruff: noqa: E501

BENCHMARK_CASES = [
    # =====================================================================
    # Category A: Popular libraries (10) — stress core pipeline
    # =====================================================================
    {
        "id": "fastapi",
        "library": "fastapi",
        "query": "CORS middleware configuration",
        "tests_aspect": "i18n GitHub raw filtering (de/ja/zh translations)",
        "expect_lang": "en",
        "expect_no_patterns": ["/de/", "/ja/", "/zh/", "/ko/"],
    },
    {
        "id": "react",
        "library": "react",
        "query": "useState useEffect hooks",
        "tests_aspect": "internal docs skip -> Tier 2 crawl (react.dev)",
        "expect_url_contains": "react.dev",
    },
    {
        "id": "django",
        "library": "django",
        "query": "database models and migrations",
        "tests_aspect": "crawl i18n URL filtering + depth-2 crawling",
        "expect_lang": "en",
        "expect_no_patterns": ["/ja/", "/el/", "/fr/", "/es/"],
    },
    {
        "id": "polars",
        "library": "polars",
        "query": "lazy frame filter group_by",
        "tests_aspect": "macro-heavy fallthrough to Tier 2 crawl",
        "expect_no_patterns": ["{{", "code_block("],
    },
    {
        "id": "pydantic",
        "library": "pydantic",
        "query": "field_validator custom validation",
        "tests_aspect": "FTS heading weight balance (content vs heading)",
        "expect_top_relevant": True,
    },
    {
        "id": "nextjs",
        "library": "next",
        "query": "server components data fetching",
        "tests_aspect": "large docs site with many pages",
    },
    {
        "id": "vue",
        "library": "vue",
        "query": "composition API reactive refs",
        "tests_aspect": "i18n (vuejs.org has translations)",
        "expect_lang": "en",
    },
    {
        "id": "sqlalchemy",
        "library": "sqlalchemy",
        "query": "ORM relationships one-to-many",
        "tests_aspect": "version prefix crawl restriction",
    },
    {
        "id": "tailwindcss",
        "library": "tailwindcss",
        "query": "flexbox grid layout utilities",
        "tests_aspect": "nav heading block stripping",
        "expect_no_nav_titles": True,
    },
    {
        "id": "langchain",
        "library": "langchain",
        "query": "retrieval chain vector store",
        "tests_aspect": "quality gate <20 chunks -> Tier 2 fallthrough",
    },
    # =====================================================================
    # Category B: Medium popularity (10) — diverse ecosystems
    # =====================================================================
    {
        "id": "hono",
        "library": "hono",
        "query": "middleware routing context",
        "tests_aspect": "TypeScript web framework (npm, llms.txt)",
    },
    {
        "id": "effect",
        "library": "effect",
        "query": "error handling pipe effect",
        "tests_aspect": "TypeScript functional (llms.txt)",
    },
    {
        "id": "ruff",
        "library": "ruff",
        "query": "configuration rules select ignore",
        "tests_aspect": "Rust-based Python tool (PyPI, GitHub raw)",
    },
    {
        "id": "duckdb",
        "library": "duckdb",
        "query": "SQL queries parquet files",
        "tests_aspect": "multi-language bindings docs (landing page fix)",
    },
    {
        "id": "meilisearch",
        "library": "meilisearch",
        "query": "search index settings filters",
        "tests_aspect": "SearXNG fallback (SDK vs server docs)",
    },
    {
        "id": "prisma",
        "library": "prisma",
        "query": "schema models client queries relations",
        "tests_aspect": "npm ORM with prisma.io docs",
    },
    {
        "id": "fastify",
        "library": "fastify",
        "query": "plugins hooks decorators routes",
        "tests_aspect": "npm, fastify.dev",
    },
    {
        "id": "angular",
        "library": "@angular/core",
        "query": "components services dependency injection",
        "tests_aspect": "scoped npm, angular.dev",
    },
    {
        "id": "svelte",
        "library": "svelte",
        "query": "reactivity stores components",
        "tests_aspect": "npm, svelte.dev",
    },
    {
        "id": "astro",
        "library": "astro",
        "query": "content collections islands architecture",
        "tests_aspect": "npm, astro.build, llms.txt expected",
    },
    # =====================================================================
    # Category C: Python ecosystem (10) — PyPI discovery
    # =====================================================================
    {
        "id": "flask",
        "library": "flask",
        "query": "blueprints application factory routing",
        "tests_aspect": "PyPI, ReadTheDocs",
    },
    {
        "id": "pytorch",
        "library": "torch",
        "query": "tensor operations autograd backward",
        "tests_aspect": "PyPI vs npm name collision",
    },
    {
        "id": "pytest",
        "library": "pytest",
        "query": "fixtures parametrize marks conftest",
        "tests_aspect": "PyPI, pytest.org docs",
    },
    {
        "id": "numpy",
        "library": "numpy",
        "query": "array operations broadcasting reshape",
        "tests_aspect": "PyPI, numpy.org large docs",
    },
    {
        "id": "pandas",
        "library": "pandas",
        "query": "dataframe groupby merge pivot",
        "tests_aspect": "PyPI, pandas.pydata.org",
    },
    {
        "id": "scikit-learn",
        "library": "scikit-learn",
        "query": "classification random forest fit predict",
        "tests_aspect": "hyphenated PyPI name",
    },
    {
        "id": "requests",
        "library": "requests",
        "query": "session authentication headers timeout",
        "tests_aspect": "PyPI, very popular, ReadTheDocs",
    },
    {
        "id": "celery",
        "library": "celery",
        "query": "task queue workers beat schedule",
        "tests_aspect": "PyPI, celeryproject.org docs",
    },
    {
        "id": "httpx",
        "library": "httpx",
        "query": "async client streaming timeout",
        "tests_aspect": "PyPI, modern async HTTP",
    },
    {
        "id": "typer",
        "library": "typer",
        "query": "CLI commands options arguments callback",
        "tests_aspect": "PyPI, tiangolo ecosystem",
    },
    # =====================================================================
    # Category D: Lesser-known / niche (10) — edge cases
    # =====================================================================
    {
        "id": "instructor",
        "library": "instructor",
        "query": "structured output pydantic model",
        "tests_aspect": "npm deprecated detection (PyPI is correct)",
    },
    {
        "id": "litestar",
        "library": "litestar",
        "query": "route handlers dependency injection",
        "tests_aspect": "Python ASGI framework (less popular)",
    },
    {
        "id": "drizzle-orm",
        "library": "drizzle-orm",
        "query": "schema definition queries select",
        "tests_aspect": "TypeScript ORM (npm, llms.txt)",
    },
    {
        "id": "tanstack-query",
        "library": "@tanstack/react-query",
        "query": "useQuery mutations invalidation",
        "tests_aspect": "framework path filtering (react vs angular)",
    },
    {
        "id": "crawl4ai",
        "library": "crawl4ai",
        "query": "async web crawler extraction config",
        "tests_aspect": "npm wrapper vs PyPI original",
    },
    {
        "id": "zod",
        "library": "zod",
        "query": "schema validation parse safeParse",
        "tests_aspect": "npm small TS validation lib",
    },
    {
        "id": "htmx",
        "library": "htmx.org",
        "query": "hx-get hx-post hx-swap attributes",
        "tests_aspect": "htmx.org (CDN-based, no npm install)",
    },
    {
        "id": "elysia",
        "library": "elysia",
        "query": "routes plugins lifecycle hooks",
        "tests_aspect": "Bun web framework (newer npm)",
    },
    {
        "id": "playwright",
        "library": "playwright",
        "query": "page locator click assertions",
        "tests_aspect": "npm, playwright.dev, cross-language",
    },
    {
        "id": "remix",
        "library": "@remix-run/react",
        "query": "loaders actions routes outlet",
        "tests_aspect": "scoped npm, remix.run docs",
    },
    # =====================================================================
    # Category E: Rust & Go (10) — crates.io / Go discovery
    # =====================================================================
    {
        "id": "tokio",
        "library": "tokio",
        "query": "async runtime spawn tasks select",
        "tests_aspect": "crates.io, tokio.rs docs",
    },
    {
        "id": "axum",
        "library": "axum",
        "query": "router extractors handlers middleware",
        "tests_aspect": "crates.io, small Rust web",
    },
    {
        "id": "serde",
        "library": "serde",
        "query": "serialize deserialize derive attributes",
        "tests_aspect": "crates.io, serde.rs",
    },
    {
        "id": "gin",
        "library": "gin",
        "query": "router middleware groups context JSON",
        "tests_aspect": "Go web framework (npm collision likely)",
    },
    {
        "id": "echo-go",
        "library": "echo",
        "query": "routes middleware context request response",
        "tests_aspect": "Go web framework (npm collision likely)",
    },
    {
        "id": "trpc",
        "library": "@trpc/server",
        "query": "router procedures middleware context",
        "tests_aspect": "scoped npm, tRPC monorepo",
    },
    {
        "id": "sveltekit",
        "library": "@sveltejs/kit",
        "query": "load functions form actions hooks",
        "tests_aspect": "scoped npm, kit.svelte.dev",
    },
    {
        "id": "uvicorn",
        "library": "uvicorn",
        "query": "ASGI server configuration workers reload",
        "tests_aspect": "PyPI, ASGI server docs",
    },
    {
        "id": "shadcn-ui",
        "library": "shadcn-ui",
        "query": "button dialog components installation",
        "tests_aspect": "not a real npm package (copy-paste CLI)",
    },
    {
        "id": "playwright-python",
        "library": "playwright",
        "query": "page locator click assertions browser",
        "tests_aspect": "PyPI playwright, cross-lang (same name as npm)",
    },
]


def get_benchmark_ids() -> list[str]:
    """Return all benchmark case IDs."""
    return [str(c["id"]) for c in BENCHMARK_CASES]


def get_case(case_id: str) -> dict:
    """Get a benchmark case by ID."""
    for c in BENCHMARK_CASES:
        if c["id"] == case_id:
            return c
    raise ValueError(f"Unknown benchmark case: {case_id}")
