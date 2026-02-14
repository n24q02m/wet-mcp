"""Benchmark test suite for docs search quality (120 libraries).

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
        "tests_aspect": "Go web framework (npm/pypi collision, star-count disambiguation)",
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
    # =====================================================================
    # Category F: Frontend frameworks & UI (10) — npm scoped + UI libs
    # =====================================================================
    {
        "id": "solidjs",
        "library": "solid-js",
        "query": "createSignal createEffect reactivity",
        "tests_aspect": "npm, solidjs.com (hyphenated name)",
    },
    {
        "id": "qwik",
        "library": "@builder.io/qwik",
        "query": "component$ useSignal routing",
        "tests_aspect": "deeply scoped npm, qwik.dev",
    },
    {
        "id": "nuxt",
        "library": "nuxt",
        "query": "pages routing composables useFetch",
        "tests_aspect": "npm, nuxt.com (Vue meta-framework)",
    },
    {
        "id": "preact",
        "library": "preact",
        "query": "hooks useState component rendering",
        "tests_aspect": "npm, preactjs.com (lightweight React alternative)",
    },
    {
        "id": "alpinejs",
        "library": "alpinejs",
        "query": "x-data x-on x-bind directives",
        "tests_aspect": "npm, alpinejs.dev (minimal JS framework)",
    },
    {
        "id": "lit",
        "library": "lit",
        "query": "LitElement html css reactive properties",
        "tests_aspect": "npm, lit.dev (Web Components)",
    },
    {
        "id": "mui-material",
        "library": "@mui/material",
        "query": "Button TextField theme customization",
        "tests_aspect": "scoped npm, mui.com (large component lib)",
    },
    {
        "id": "mantine",
        "library": "@mantine/core",
        "query": "Button Input Modal hooks theme",
        "tests_aspect": "scoped npm, mantine.dev",
    },
    {
        "id": "chakra-ui",
        "library": "@chakra-ui/react",
        "query": "Box Flex theme provider responsive",
        "tests_aspect": "scoped npm, chakra-ui.com",
    },
    {
        "id": "threejs",
        "library": "three",
        "query": "scene camera renderer mesh geometry",
        "tests_aspect": "npm, threejs.org (WebGL, name != pkg)",
    },
    # =====================================================================
    # Category G: Backend & API (10) — diverse server frameworks
    # =====================================================================
    {
        "id": "express",
        "library": "express",
        "query": "middleware routing error handling",
        "tests_aspect": "npm, expressjs.com (most popular Node.js)",
    },
    {
        "id": "koa",
        "library": "koa",
        "query": "context middleware cascade error",
        "tests_aspect": "npm, koajs.com (lightweight Node.js)",
    },
    {
        "id": "nestjs",
        "library": "@nestjs/core",
        "query": "controllers providers modules guards",
        "tests_aspect": "scoped npm, docs.nestjs.com",
    },
    {
        "id": "starlette",
        "library": "starlette",
        "query": "routes middleware WebSocket responses",
        "tests_aspect": "PyPI, ASGI framework (fastapi base)",
    },
    {
        "id": "sanic",
        "library": "sanic",
        "query": "handlers blueprints middleware streaming",
        "tests_aspect": "PyPI, sanicframework.org (async Python)",
    },
    {
        "id": "aiohttp",
        "library": "aiohttp",
        "query": "client session server routes WebSocket",
        "tests_aspect": "PyPI, aiohttp.readthedocs.io",
    },
    {
        "id": "drf",
        "library": "djangorestframework",
        "query": "serializers viewsets routers permissions",
        "tests_aspect": "PyPI, django-rest-framework.org (name != import)",
    },
    {
        "id": "graphql-js",
        "library": "graphql",
        "query": "schema types resolvers queries mutations",
        "tests_aspect": "npm graphql, graphql.org (generic name)",
    },
    {
        "id": "socketio",
        "library": "socket.io",
        "query": "emit rooms namespaces events broadcast",
        "tests_aspect": "npm, socket.io (dotted package name)",
    },
    {
        "id": "actix-web",
        "library": "actix-web",
        "query": "handlers extractors middleware state",
        "tests_aspect": "crates.io, actix.rs (Rust web framework)",
    },
    # =====================================================================
    # Category H: Data & ML (10) — Python scientific ecosystem
    # =====================================================================
    {
        "id": "transformers",
        "library": "transformers",
        "query": "pipeline AutoModel tokenizer training",
        "tests_aspect": "PyPI, huggingface.co (large docs)",
    },
    {
        "id": "tensorflow",
        "library": "tensorflow",
        "query": "keras model layers training compile",
        "tests_aspect": "PyPI, tensorflow.org (massive docs)",
    },
    {
        "id": "scipy",
        "library": "scipy",
        "query": "optimize interpolate integrate stats",
        "tests_aspect": "PyPI, scipy.org (scientific computing)",
    },
    {
        "id": "matplotlib",
        "library": "matplotlib",
        "query": "plot figure axes subplot legend",
        "tests_aspect": "PyPI, matplotlib.org (visualization)",
    },
    {
        "id": "seaborn",
        "library": "seaborn",
        "query": "heatmap scatter violin distribution",
        "tests_aspect": "PyPI, seaborn.pydata.org (stats viz)",
    },
    {
        "id": "spacy",
        "library": "spacy",
        "query": "nlp pipeline ner tokenization models",
        "tests_aspect": "PyPI, spacy.io (NLP library)",
    },
    {
        "id": "opencv",
        "library": "opencv-python",
        "query": "image processing video capture contours",
        "tests_aspect": "PyPI, opencv.org (name != import)",
    },
    {
        "id": "pillow",
        "library": "pillow",
        "query": "Image open resize filter save",
        "tests_aspect": "PyPI, pillow.readthedocs.io (PIL fork)",
    },
    {
        "id": "sympy",
        "library": "sympy",
        "query": "symbols solve integrate simplify",
        "tests_aspect": "PyPI, sympy.org (symbolic math)",
    },
    {
        "id": "nltk",
        "library": "nltk",
        "query": "tokenize corpus pos_tag sentiment",
        "tests_aspect": "PyPI, nltk.org (classic NLP toolkit)",
    },
    # =====================================================================
    # Category I: DevTools & Build (10) — JavaScript tooling
    # =====================================================================
    {
        "id": "webpack",
        "library": "webpack",
        "query": "loaders plugins entry output config",
        "tests_aspect": "npm, webpack.js.org (bundler)",
    },
    {
        "id": "esbuild",
        "library": "esbuild",
        "query": "build transform bundle plugins",
        "tests_aspect": "npm, esbuild.github.io (Go-based bundler)",
    },
    {
        "id": "vite",
        "library": "vite",
        "query": "dev server plugins HMR config build",
        "tests_aspect": "npm, vite.dev (modern build tool)",
    },
    {
        "id": "jest",
        "library": "jest",
        "query": "matchers mocks describe expect beforeEach",
        "tests_aspect": "npm, jestjs.io (testing framework)",
    },
    {
        "id": "cypress",
        "library": "cypress",
        "query": "commands visit click intercept assertions",
        "tests_aspect": "npm, docs.cypress.io (E2E testing)",
    },
    {
        "id": "prettier",
        "library": "prettier",
        "query": "options plugins configuration ignore",
        "tests_aspect": "npm, prettier.io (code formatter)",
    },
    {
        "id": "biome",
        "library": "@biomejs/biome",
        "query": "lint format rules configuration",
        "tests_aspect": "scoped npm, biomejs.dev (linter+formatter)",
    },
    {
        "id": "turbo",
        "library": "turbo",
        "query": "pipeline tasks caching remote cache",
        "tests_aspect": "npm, turbo.build (monorepo build)",
    },
    {
        "id": "rollup",
        "library": "rollup",
        "query": "plugins input output format treeshaking",
        "tests_aspect": "npm, rollupjs.org (ES module bundler)",
    },
    {
        "id": "vitest",
        "library": "vitest",
        "query": "describe it expect mock coverage",
        "tests_aspect": "npm, vitest.dev (Vite test runner)",
    },
    # =====================================================================
    # Category J: Rust & Go ecosystem (10) — crates.io / Go edge cases
    # =====================================================================
    {
        "id": "fiber",
        "library": "fiber",
        "query": "router middleware handlers context JSON",
        "tests_aspect": "Go, gofiber.io (generic name like echo)",
    },
    {
        "id": "chi",
        "library": "chi",
        "query": "router middleware mux handlers subrouter",
        "tests_aspect": "Go, go-chi.io (very generic name)",
    },
    {
        "id": "bevy",
        "library": "bevy",
        "query": "ECS components systems queries plugins",
        "tests_aspect": "crates.io, bevyengine.org (game engine)",
    },
    {
        "id": "clap",
        "library": "clap",
        "query": "derive arguments subcommand parser",
        "tests_aspect": "crates.io, clap.rs (CLI arg parser)",
    },
    {
        "id": "reqwest",
        "library": "reqwest",
        "query": "client get post async request",
        "tests_aspect": "crates.io (similar to requests, unique name)",
    },
    {
        "id": "diesel",
        "library": "diesel",
        "query": "query schema migrations insert select",
        "tests_aspect": "crates.io, diesel.rs (Rust ORM)",
    },
    {
        "id": "rocket",
        "library": "rocket",
        "query": "routes handlers guards state fairings",
        "tests_aspect": "crates.io, rocket.rs (Rust web, generic name)",
    },
    {
        "id": "warp",
        "library": "warp",
        "query": "filters routes rejection handlers",
        "tests_aspect": "crates.io (Rust web, very generic name)",
    },
    {
        "id": "iced",
        "library": "iced",
        "query": "Application widget view update message",
        "tests_aspect": "crates.io (Rust GUI, generic name)",
    },
    {
        "id": "tauri-rs",
        "library": "tauri",
        "query": "commands events window IPC plugins",
        "tests_aspect": "npm + crates.io cross-ecosystem, tauri.app",
    },
    # =====================================================================
    # Category K: Cloud & Infrastructure (10) — SDKs, CLIs, cloud tools
    # =====================================================================
    {
        "id": "terraform-cdk",
        "library": "cdktf",
        "query": "providers stacks constructs synth deploy",
        "tests_aspect": "npm, Terraform CDK for TypeScript",
    },
    {
        "id": "pulumi",
        "library": "pulumi",
        "query": "stack resource output config provider",
        "tests_aspect": "npm/pypi, pulumi.com (IaC tool)",
    },
    {
        "id": "boto3",
        "library": "boto3",
        "query": "s3 client resource session ec2",
        "tests_aspect": "PyPI, AWS SDK for Python",
    },
    {
        "id": "supabase-js",
        "library": "supabase",
        "query": "auth database storage realtime edge functions",
        "tests_aspect": "npm, supabase.com (BaaS)",
    },
    {
        "id": "firebase-admin",
        "library": "firebase-admin",
        "query": "auth firestore messaging cloud functions",
        "tests_aspect": "npm/pypi, Firebase Admin SDK",
    },
    {
        "id": "redis-py",
        "library": "redis",
        "query": "connection pool pipeline pub sub cluster",
        "tests_aspect": "PyPI, redis.io (generic name collision npm vs pypi)",
    },
    {
        "id": "celery-beat",
        "library": "django-celery-beat",
        "query": "periodic tasks schedule crontab interval",
        "tests_aspect": "PyPI, django-celery-beat (long name, unique)",
    },
    {
        "id": "docker-py",
        "library": "docker",
        "query": "containers images volumes networks build",
        "tests_aspect": "PyPI docker SDK (generic name)",
    },
    {
        "id": "kubernetes-client",
        "library": "kubernetes",
        "query": "pods deployments services config client",
        "tests_aspect": "PyPI, kubernetes.io (generic name)",
    },
    {
        "id": "httpie",
        "library": "httpie",
        "query": "request headers auth plugins sessions",
        "tests_aspect": "PyPI, httpie.io (CLI HTTP client)",
    },
    # =====================================================================
    # Category L: Emerging & Niche (10) — newer/niche libraries
    # =====================================================================
    {
        "id": "pnpm",
        "library": "pnpm",
        "query": "workspace install link peer dependencies",
        "tests_aspect": "npm, pnpm.io (package manager, unique name)",
    },
    {
        "id": "deno",
        "library": "deno",
        "query": "permissions runtime deploy fresh",
        "tests_aspect": "npm, deno.land (JS runtime)",
    },
    {
        "id": "lodash",
        "library": "lodash",
        "query": "debounce throttle merge cloneDeep",
        "tests_aspect": "npm, lodash.com (JS utility, well-known)",
    },
    {
        "id": "motion",
        "library": "motion",
        "query": "animate transition gesture spring keyframes",
        "tests_aspect": "npm, motion.dev (animation library, ex-framer-motion)",
    },
    {
        "id": "cheerio",
        "library": "cheerio",
        "query": "selector parse html load find",
        "tests_aspect": "npm, cheerio.js.org (HTML parser)",
    },
    {
        "id": "sqlx",
        "library": "sqlx",
        "query": "query pool connection migrate transaction",
        "tests_aspect": "crates.io, github.com/launchbadge/sqlx (Rust async SQL)",
    },
    {
        "id": "salvo",
        "library": "salvo",
        "query": "router handler depot request response",
        "tests_aspect": "crates.io, salvo.rs (Rust web framework)",
    },
    {
        "id": "sea-orm",
        "library": "sea-orm",
        "query": "entity model migration query builder",
        "tests_aspect": "crates.io, sea-ql.org (Rust ORM, unique name)",
    },
    {
        "id": "dayjs",
        "library": "dayjs",
        "query": "format parse timezone locale plugin",
        "tests_aspect": "npm, day.js.org (date library, unique name)",
    },
    {
        "id": "ultralytics",
        "library": "ultralytics",
        "query": "yolo detect train predict export model",
        "tests_aspect": "PyPI, ultralytics.com (YOLO object detection)",
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
