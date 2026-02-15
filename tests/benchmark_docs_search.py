"""Benchmark test suite for docs search quality (300 libraries).

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
    # =====================================================================
    # Category M: Auth & Security (10) — authentication/authorization libs
    # =====================================================================
    {
        "id": "passportjs",
        "library": "passport",
        "query": "strategy authenticate session serialize",
        "tests_aspect": "npm, passportjs.org (Node.js auth middleware)",
    },
    {
        "id": "nextauth",
        "library": "next-auth",
        "query": "providers session callbacks credentials JWT",
        "tests_aspect": "npm, authjs.dev (Next.js auth, renamed)",
    },
    {
        "id": "jose",
        "library": "jose",
        "query": "JWT sign verify encrypt JWK JWS",
        "tests_aspect": "npm, JOSE/JWT library (short generic name)",
    },
    {
        "id": "bcrypt",
        "library": "bcrypt",
        "query": "hash compare salt rounds password",
        "tests_aspect": "npm, bcrypt (password hashing, generic name)",
    },
    {
        "id": "authlib",
        "library": "authlib",
        "query": "OAuth2 client OIDC JWT bearer token",
        "tests_aspect": "PyPI, authlib.org (Python OAuth library)",
    },
    {
        "id": "python-jose",
        "library": "python-jose",
        "query": "JWT encode decode claims algorithms",
        "tests_aspect": "PyPI, python-jose (Python JWT, hyphenated name)",
    },
    {
        "id": "helmet",
        "library": "helmet",
        "query": "CSP headers security HSTS frameguard",
        "tests_aspect": "npm, helmetjs.github.io (HTTP security headers)",
    },
    {
        "id": "cors",
        "library": "cors",
        "query": "origin methods headers credentials preflight",
        "tests_aspect": "npm, expressjs/cors (very short generic name)",
    },
    {
        "id": "cryptography",
        "library": "cryptography",
        "query": "Fernet symmetric asymmetric certificates X509",
        "tests_aspect": "PyPI, cryptography.io (Python crypto library)",
    },
    {
        "id": "argon2",
        "library": "argon2-cffi",
        "query": "hash verify password PasswordHasher",
        "tests_aspect": "PyPI, argon2-cffi (Argon2 bindings, hyphenated)",
    },
    # =====================================================================
    # Category N: Database & ORM (10) — database drivers and ORMs
    # =====================================================================
    {
        "id": "typeorm",
        "library": "typeorm",
        "query": "entity repository migration query builder",
        "tests_aspect": "npm, typeorm.io (TypeScript ORM)",
    },
    {
        "id": "sequelize",
        "library": "sequelize",
        "query": "model define associations migration findAll",
        "tests_aspect": "npm, sequelize.org (Node.js ORM)",
    },
    {
        "id": "mongoose",
        "library": "mongoose",
        "query": "schema model query populate middleware",
        "tests_aspect": "npm, mongoosejs.com (MongoDB ODM)",
    },
    {
        "id": "sqlmodel",
        "library": "sqlmodel",
        "query": "table model select session relationship",
        "tests_aspect": "PyPI, sqlmodel.tiangolo.com (Pydantic + SQLAlchemy)",
    },
    {
        "id": "peewee",
        "library": "peewee",
        "query": "model fields query select create",
        "tests_aspect": "PyPI, docs.peewee-orm.com (lightweight Python ORM)",
    },
    {
        "id": "knex",
        "library": "knex",
        "query": "query builder migration schema join where",
        "tests_aspect": "npm, knexjs.org (SQL query builder)",
    },
    {
        "id": "kysely",
        "library": "kysely",
        "query": "query builder type-safe select insert migration",
        "tests_aspect": "npm, kysely.dev (type-safe TS SQL builder)",
    },
    {
        "id": "alembic",
        "library": "alembic",
        "query": "migration revision upgrade downgrade autogenerate",
        "tests_aspect": "PyPI, alembic.sqlalchemy.org (SQLAlchemy migrations)",
    },
    {
        "id": "motor",
        "library": "motor",
        "query": "async MongoDB client collection find insert",
        "tests_aspect": "PyPI, motor.readthedocs.io (async MongoDB driver)",
    },
    {
        "id": "ioredis",
        "library": "ioredis",
        "query": "client cluster pipeline subscribe pub",
        "tests_aspect": "npm, ioredis (Redis client for Node.js)",
    },
    # =====================================================================
    # Category O: CLI & Terminal (10) — command line tools & TUI libs
    # =====================================================================
    {
        "id": "click",
        "library": "click",
        "query": "command group option argument callback",
        "tests_aspect": "PyPI, click.palletsprojects.com (Python CLI, very popular)",
    },
    {
        "id": "rich",
        "library": "rich",
        "query": "console table progress panel syntax",
        "tests_aspect": "PyPI, rich.readthedocs.io (terminal formatting)",
    },
    {
        "id": "inquirer",
        "library": "@inquirer/prompts",
        "query": "input select confirm checkbox password",
        "tests_aspect": "scoped npm, inquirer (interactive CLI prompts)",
    },
    {
        "id": "commander",
        "library": "commander",
        "query": "program command option argument action",
        "tests_aspect": "npm, commander.js (Node.js CLI framework)",
    },
    {
        "id": "yargs",
        "library": "yargs",
        "query": "command options positional middleware help",
        "tests_aspect": "npm, yargs.js.org (CLI parser)",
    },
    {
        "id": "textual",
        "library": "textual",
        "query": "App Widget Screen compose mount",
        "tests_aspect": "PyPI, textual.textualize.io (Python TUI framework)",
    },
    {
        "id": "tqdm",
        "library": "tqdm",
        "query": "progress bar iterator wrap notebook",
        "tests_aspect": "PyPI, tqdm.github.io (progress bar, short name)",
    },
    {
        "id": "chalk",
        "library": "chalk",
        "query": "color red green bold underline hex",
        "tests_aspect": "npm, chalk (terminal colors, generic name)",
    },
    {
        "id": "argparse",
        "library": "argparse",
        "query": "parser argument add subparser",
        "tests_aspect": "PyPI/stdlib, very generic name",
    },
    {
        "id": "blessed",
        "library": "blessed",
        "query": "screen box terminal cursor input",
        "tests_aspect": "npm, blessed (terminal UI, generic name)",
    },
    # =====================================================================
    # Category P: Testing & QA (10) — test frameworks and tools
    # =====================================================================
    {
        "id": "mocha",
        "library": "mocha",
        "query": "describe it before after hooks reporter",
        "tests_aspect": "npm, mochajs.org (Node.js test framework)",
    },
    {
        "id": "chai",
        "library": "chai",
        "query": "expect should assert deep equal include",
        "tests_aspect": "npm, chaijs.com (assertion library, short name)",
    },
    {
        "id": "supertest",
        "library": "supertest",
        "query": "request app get post expect status",
        "tests_aspect": "npm, supertest (HTTP assertions)",
    },
    {
        "id": "nock",
        "library": "nock",
        "query": "intercept mock HTTP scope reply",
        "tests_aspect": "npm, nock (HTTP mocking, short name)",
    },
    {
        "id": "faker",
        "library": "@faker-js/faker",
        "query": "name email address phone random seed",
        "tests_aspect": "scoped npm, fakerjs.dev (data generation)",
    },
    {
        "id": "hypothesis",
        "library": "hypothesis",
        "query": "given strategies example settings assume",
        "tests_aspect": "PyPI, hypothesis.readthedocs.io (property-based testing)",
    },
    {
        "id": "factory-boy",
        "library": "factory-boy",
        "query": "Factory SubFactory Sequence LazyAttribute",
        "tests_aspect": "PyPI, factory-boy (test fixtures, hyphenated)",
    },
    {
        "id": "responses",
        "library": "responses",
        "query": "mock activate add callback passthrough",
        "tests_aspect": "PyPI, responses (HTTP mocking for requests)",
    },
    {
        "id": "coverage",
        "library": "coverage",
        "query": "run report html combine source branch",
        "tests_aspect": "PyPI, coverage.readthedocs.io (code coverage)",
    },
    {
        "id": "storybook",
        "library": "storybook",
        "query": "stories args decorators addon controls",
        "tests_aspect": "npm, storybook.js.org (UI component testing)",
    },
    # =====================================================================
    # Category Q: State Management & Data Flow (10) — state, stores, events
    # =====================================================================
    {
        "id": "zustand",
        "library": "zustand",
        "query": "create store set get subscribe middleware",
        "tests_aspect": "npm, zustand (React state, unique name)",
    },
    {
        "id": "redux-toolkit",
        "library": "@reduxjs/toolkit",
        "query": "createSlice configureStore createAsyncThunk",
        "tests_aspect": "scoped npm, redux-toolkit.js.org",
    },
    {
        "id": "jotai",
        "library": "jotai",
        "query": "atom useAtom Provider atomWithStorage",
        "tests_aspect": "npm, jotai.org (atomic state, unique name)",
    },
    {
        "id": "pinia",
        "library": "pinia",
        "query": "defineStore state getters actions plugins",
        "tests_aspect": "npm, pinia.vuejs.org (Vue state management)",
    },
    {
        "id": "mobx",
        "library": "mobx",
        "query": "observable action computed reaction autorun",
        "tests_aspect": "npm, mobx.js.org (reactive state)",
    },
    {
        "id": "rxjs",
        "library": "rxjs",
        "query": "Observable pipe map filter switchMap Subject",
        "tests_aspect": "npm, rxjs.dev (reactive extensions)",
    },
    {
        "id": "recoil",
        "library": "recoil",
        "query": "atom selector useRecoilState RecoilRoot",
        "tests_aspect": "npm, recoiljs.org (React state by Meta)",
    },
    {
        "id": "valtio",
        "library": "valtio",
        "query": "proxy useSnapshot subscribe ref",
        "tests_aspect": "npm, valtio (proxy-based state, unique name)",
    },
    {
        "id": "ngrx-store",
        "library": "@ngrx/store",
        "query": "reducer action selector effects createFeature",
        "tests_aspect": "scoped npm, ngrx.io (Angular state management)",
    },
    {
        "id": "xstate",
        "library": "xstate",
        "query": "machine state transition context actions guards",
        "tests_aspect": "npm, xstate.js.org (state machines)",
    },
    # =====================================================================
    # Category R: Networking & HTTP (10) — HTTP clients, WebSocket, gRPC
    # =====================================================================
    {
        "id": "axios",
        "library": "axios",
        "query": "get post interceptors config instance",
        "tests_aspect": "npm, axios-http.com (HTTP client)",
    },
    {
        "id": "got",
        "library": "got",
        "query": "request retry hooks pagination stream",
        "tests_aspect": "npm, got (HTTP client, very short name)",
    },
    {
        "id": "undici",
        "library": "undici",
        "query": "fetch request client pool dispatcher",
        "tests_aspect": "npm, undici (Node.js HTTP/1.1 client)",
    },
    {
        "id": "ws",
        "library": "ws",
        "query": "WebSocket server client send message",
        "tests_aspect": "npm, ws (WebSocket, ultra-short 2-char name)",
    },
    {
        "id": "grpcio",
        "library": "grpcio",
        "query": "server channel stub service interceptor",
        "tests_aspect": "PyPI, grpc.io (gRPC Python bindings)",
    },
    {
        "id": "urllib3",
        "library": "urllib3",
        "query": "pool manager request retry timeout",
        "tests_aspect": "PyPI, urllib3.readthedocs.io (HTTP library)",
    },
    {
        "id": "node-fetch",
        "library": "node-fetch",
        "query": "fetch response headers body stream",
        "tests_aspect": "npm, node-fetch (polyfill, hyphenated name)",
    },
    {
        "id": "twisted",
        "library": "twisted",
        "query": "reactor protocol factory deferred endpoint",
        "tests_aspect": "PyPI, twisted.org (async networking)",
    },
    {
        "id": "httptools",
        "library": "httptools",
        "query": "parser HttpRequestParser protocol",
        "tests_aspect": "PyPI, httptools (HTTP parser, generic name)",
    },
    {
        "id": "ky",
        "library": "ky",
        "query": "get post hooks retry timeout prefixUrl",
        "tests_aspect": "npm, ky (HTTP client, ultra-short 2-char name)",
    },
    # =====================================================================
    # Category S: Validation & Serialization (10) — schemas, parsing, codegen
    # =====================================================================
    {
        "id": "joi",
        "library": "joi",
        "query": "schema object string number validate alternatives",
        "tests_aspect": "npm, joi.dev (validation, very short name)",
    },
    {
        "id": "yup",
        "library": "yup",
        "query": "schema object string required validate cast",
        "tests_aspect": "npm, yup (validation, very short name)",
    },
    {
        "id": "ajv",
        "library": "ajv",
        "query": "schema validate compile error format",
        "tests_aspect": "npm, ajv.js.org (JSON Schema validator, short name)",
    },
    {
        "id": "marshmallow",
        "library": "marshmallow",
        "query": "Schema fields dump load validate nested",
        "tests_aspect": "PyPI, marshmallow.readthedocs.io (serialization)",
    },
    {
        "id": "msgpack",
        "library": "msgpack",
        "query": "pack unpack Packer Unpacker raw",
        "tests_aspect": "PyPI/npm, msgpack.org (binary serialization)",
    },
    {
        "id": "protobuf",
        "library": "protobuf",
        "query": "message field service enum compile",
        "tests_aspect": "PyPI/npm, protobuf.dev (Protocol Buffers)",
    },
    {
        "id": "valibot",
        "library": "valibot",
        "query": "schema object string parse safeParse pipe",
        "tests_aspect": "npm, valibot.dev (TS schema validation, unique name)",
    },
    {
        "id": "typebox",
        "library": "@sinclair/typebox",
        "query": "Type Object String Number Static Value",
        "tests_aspect": "scoped npm, typebox (JSON Schema type builder)",
    },
    {
        "id": "cattrs",
        "library": "cattrs",
        "query": "structure unstructure converter hook",
        "tests_aspect": "PyPI, cattrs.readthedocs.io (attrs serialization)",
    },
    {
        "id": "orjson",
        "library": "orjson",
        "query": "dumps loads OPT_INDENT OPT_SORT_KEYS",
        "tests_aspect": "PyPI, orjson (fast JSON, unique name)",
    },
    # =====================================================================
    # Category T: Logging, Config & Utilities (10) — cross-cutting concerns
    # =====================================================================
    {
        "id": "winston",
        "library": "winston",
        "query": "logger transport format level createLogger",
        "tests_aspect": "npm, winston (Node.js logging, unique name)",
    },
    {
        "id": "pino",
        "library": "pino",
        "query": "logger child transport destination level",
        "tests_aspect": "npm, getpino.io (fast Node.js logging)",
    },
    {
        "id": "loguru",
        "library": "loguru",
        "query": "logger add sink format level filter",
        "tests_aspect": "PyPI, loguru.readthedocs.io (Python logging)",
    },
    {
        "id": "dotenv",
        "library": "dotenv",
        "query": "config parse load env process.env",
        "tests_aspect": "npm, dotenv (env vars, generic name collision)",
    },
    {
        "id": "pydantic-settings",
        "library": "pydantic-settings",
        "query": "BaseSettings env_prefix env_file dotenv",
        "tests_aspect": "PyPI, pydantic-settings (settings management)",
    },
    {
        "id": "python-dotenv",
        "library": "python-dotenv",
        "query": "load_dotenv find_dotenv set_key dotenv_values",
        "tests_aspect": "PyPI, python-dotenv (env file loading)",
    },
    {
        "id": "date-fns",
        "library": "date-fns",
        "query": "format parse add differenceIn isValid",
        "tests_aspect": "npm, date-fns.org (date utility, hyphenated)",
    },
    {
        "id": "nanoid",
        "library": "nanoid",
        "query": "nanoid customAlphabet urlAlphabet random",
        "tests_aspect": "npm, nanoid (ID generator, unique name)",
    },
    {
        "id": "structlog",
        "library": "structlog",
        "query": "get_logger configure processors bind event",
        "tests_aspect": "PyPI, structlog.readthedocs.io (structured logging)",
    },
    {
        "id": "uuid",
        "library": "uuid",
        "query": "v4 v5 v7 parse validate NIL",
        "tests_aspect": "npm, uuid (UUID generator, ultra-generic name)",
    },
    # =====================================================================
    # Category U: Graphics & Media (10) — canvas, image processing, charting
    # =====================================================================
    {
        "id": "pixijs",
        "library": "pixi.js",
        "query": "Application Sprite Container Texture renderer",
        "tests_aspect": "npm, pixijs.com (2D WebGL engine, dotted name)",
    },
    {
        "id": "phaser",
        "library": "phaser",
        "query": "Scene Sprite Physics Arcade Tilemap",
        "tests_aspect": "npm, phaser.io (HTML5 game framework)",
    },
    {
        "id": "konva",
        "library": "konva",
        "query": "Stage Layer Shape Rect Circle drag",
        "tests_aspect": "npm, konvajs.org (canvas 2D library)",
    },
    {
        "id": "fabricjs",
        "library": "fabric",
        "query": "Canvas Object Rect Circle path event",
        "tests_aspect": "npm, fabricjs.com (canvas library, generic name)",
    },
    {
        "id": "sharp",
        "library": "sharp",
        "query": "resize rotate crop composite format metadata",
        "tests_aspect": "npm, sharp.pixelplumbing.com (image processing)",
    },
    {
        "id": "jimp",
        "library": "jimp",
        "query": "read resize crop blur composite write",
        "tests_aspect": "npm, jimp (JS image manipulation, unique name)",
    },
    {
        "id": "p5js",
        "library": "p5",
        "query": "setup draw createCanvas ellipse rect fill",
        "tests_aspect": "npm, p5js.org (creative coding, short name)",
    },
    {
        "id": "d3",
        "library": "d3",
        "query": "select scale axis transition svg path",
        "tests_aspect": "npm, d3js.org (data viz, ultra-short 2-char name)",
    },
    {
        "id": "chartjs",
        "library": "chart.js",
        "query": "Chart config data options plugins scales",
        "tests_aspect": "npm, chartjs.org (charting library, dotted name)",
    },
    {
        "id": "plotly",
        "library": "plotly",
        "query": "scatter bar heatmap layout figure subplot",
        "tests_aspect": "PyPI, plotly.com (interactive plots, multi-lang)",
    },
    # =====================================================================
    # Category V: Documentation & Static Site Generators (10)
    # =====================================================================
    {
        "id": "docusaurus",
        "library": "@docusaurus/core",
        "query": "docs blog sidebar plugin theme config",
        "tests_aspect": "scoped npm, docusaurus.io (Meta docs framework)",
    },
    {
        "id": "mkdocs",
        "library": "mkdocs",
        "query": "nav theme plugins markdown extensions",
        "tests_aspect": "PyPI, mkdocs.org (Python docs generator)",
    },
    {
        "id": "sphinx",
        "library": "sphinx",
        "query": "toctree directive extension conf.py autodoc",
        "tests_aspect": "PyPI, sphinx-doc.org (Python docs, objects.inv)",
    },
    {
        "id": "vuepress",
        "library": "vuepress",
        "query": "theme plugins config markdown frontmatter",
        "tests_aspect": "npm, vuepress.vuejs.org (Vue docs generator)",
    },
    {
        "id": "nextra",
        "library": "nextra",
        "query": "pages _meta.json callout steps tabs",
        "tests_aspect": "npm, nextra.site (Next.js docs framework)",
    },
    {
        "id": "typedoc",
        "library": "typedoc",
        "query": "entry points plugin theme options reflection",
        "tests_aspect": "npm, typedoc.org (TypeScript documentation)",
    },
    {
        "id": "starlight",
        "library": "@astrojs/starlight",
        "query": "sidebar navigation i18n components config",
        "tests_aspect": "scoped npm, starlight.astro.build (Astro docs)",
    },
    {
        "id": "redoc",
        "library": "redoc",
        "query": "OpenAPI schema theme config scrollYOffset",
        "tests_aspect": "npm, redocly.com (API docs from OpenAPI)",
    },
    {
        "id": "mintlify",
        "library": "mintlify",
        "query": "navigation api components mint.json groups",
        "tests_aspect": "npm, mintlify.com (docs platform, SaaS)",
    },
    {
        "id": "fumadocs",
        "library": "fumadocs-core",
        "query": "source loader MDX search config page",
        "tests_aspect": "npm, fumadocs.vercel.app (Next.js docs framework)",
    },
    # =====================================================================
    # Category W: Monorepo & Build Tools (10) — workspace management
    # =====================================================================
    {
        "id": "nx",
        "library": "nx",
        "query": "workspace generators executors project.json cache",
        "tests_aspect": "npm, nx.dev (monorepo build system)",
    },
    {
        "id": "lerna",
        "library": "lerna",
        "query": "publish version bootstrap link workspace",
        "tests_aspect": "npm, lerna.js.org (monorepo manager, Nrwl)",
    },
    {
        "id": "changesets",
        "library": "@changesets/cli",
        "query": "changeset version publish status init",
        "tests_aspect": "scoped npm, changesets (versioning tool)",
    },
    {
        "id": "tsup",
        "library": "tsup",
        "query": "entry format dts splitting config",
        "tests_aspect": "npm, tsup.egoist.dev (TypeScript bundler)",
    },
    {
        "id": "unbuild",
        "library": "unbuild",
        "query": "build.config entries rollup mkdist stub",
        "tests_aspect": "npm, unbuild (unified build system)",
    },
    {
        "id": "concurrently",
        "library": "concurrently",
        "query": "run parallel prefix kill-others names",
        "tests_aspect": "npm, concurrently (run parallel commands)",
    },
    {
        "id": "cross-env",
        "library": "cross-env",
        "query": "NODE_ENV set environment variable script",
        "tests_aspect": "npm, cross-env (cross-platform env vars)",
    },
    {
        "id": "syncpack",
        "library": "syncpack",
        "query": "list-mismatches fix-mismatches format semver",
        "tests_aspect": "npm, syncpack (monorepo dependency sync)",
    },
    {
        "id": "patch-package",
        "library": "patch-package",
        "query": "patch postinstall diff apply exclude",
        "tests_aspect": "npm, patch-package (patch node_modules)",
    },
    {
        "id": "pkgroll",
        "library": "pkgroll",
        "query": "exports types bin conditions build",
        "tests_aspect": "npm, pkgroll (package bundler)",
    },
    # =====================================================================
    # Category X: DevOps & Automation (10) — infra tools & task automation
    # =====================================================================
    {
        "id": "ansible",
        "library": "ansible",
        "query": "playbook inventory module task role",
        "tests_aspect": "PyPI, docs.ansible.com (IaC tool, massive docs)",
    },
    {
        "id": "paramiko",
        "library": "paramiko",
        "query": "SSHClient connect SFTPClient channel transport",
        "tests_aspect": "PyPI, paramiko.org (SSH library)",
    },
    {
        "id": "watchdog",
        "library": "watchdog",
        "query": "Observer FileSystemEventHandler events patterns",
        "tests_aspect": "PyPI, watchdog (filesystem monitoring)",
    },
    {
        "id": "schedule",
        "library": "schedule",
        "query": "every day hour minute job do run_pending",
        "tests_aspect": "PyPI, schedule (job scheduler, generic name)",
    },
    {
        "id": "apscheduler",
        "library": "apscheduler",
        "query": "scheduler trigger cron interval job store",
        "tests_aspect": "PyPI, apscheduler (advanced scheduler)",
    },
    {
        "id": "invoke",
        "library": "invoke",
        "query": "task context run collection namespace",
        "tests_aspect": "PyPI, pyinvoke.org (task runner, generic name)",
    },
    {
        "id": "fabric-py",
        "library": "fabric",
        "query": "Connection run sudo put group task",
        "tests_aspect": "PyPI, fabfile.org (SSH deployment, generic name collision)",
    },
    {
        "id": "psutil",
        "library": "psutil",
        "query": "cpu_percent virtual_memory disk_usage process",
        "tests_aspect": "PyPI, psutil (system monitoring, unique name)",
    },
    {
        "id": "sh",
        "library": "sh",
        "query": "Command bake piping redirection background",
        "tests_aspect": "PyPI, sh (subprocess wrapper, ultra-short 2-char name)",
    },
    {
        "id": "plumbum",
        "library": "plumbum",
        "query": "local path command pipeline ProcessExecutionError",
        "tests_aspect": "PyPI, plumbum (shell combinators, unique name)",
    },
    # =====================================================================
    # Category Y: Message Queues & Real-time (10) — async messaging
    # =====================================================================
    {
        "id": "bullmq",
        "library": "bullmq",
        "query": "Queue Worker FlowProducer Job connection",
        "tests_aspect": "npm, bullmq (Redis-based queue)",
    },
    {
        "id": "amqplib",
        "library": "amqplib",
        "query": "connect channel assertQueue sendToQueue consume",
        "tests_aspect": "npm, amqplib (AMQP 0-9-1 client)",
    },
    {
        "id": "kafka-python",
        "library": "kafka-python",
        "query": "KafkaProducer KafkaConsumer topic partition commit",
        "tests_aspect": "PyPI, kafka-python (Kafka client, hyphenated)",
    },
    {
        "id": "pika",
        "library": "pika",
        "query": "BlockingConnection channel basic_publish basic_consume",
        "tests_aspect": "PyPI, pika (RabbitMQ client, short name)",
    },
    {
        "id": "kombu",
        "library": "kombu",
        "query": "Connection Exchange Queue Consumer Producer",
        "tests_aspect": "PyPI, kombu (messaging library, Celery dep)",
    },
    {
        "id": "dramatiq",
        "library": "dramatiq",
        "query": "actor broker middleware message result",
        "tests_aspect": "PyPI, dramatiq.io (task processing, unique name)",
    },
    {
        "id": "rq",
        "library": "rq",
        "query": "Queue Worker job enqueue result timeout",
        "tests_aspect": "PyPI, python-rq.org (Redis queue, ultra-short name)",
    },
    {
        "id": "huey",
        "library": "huey",
        "query": "task periodic crontab RedisHuey storage",
        "tests_aspect": "PyPI, huey (lightweight task queue, unique name)",
    },
    {
        "id": "nats-py",
        "library": "nats-py",
        "query": "connect publish subscribe JetStream KeyValue",
        "tests_aspect": "PyPI, nats-py (NATS client, hyphenated)",
    },
    {
        "id": "aio-pika",
        "library": "aio-pika",
        "query": "connect_robust Queue Exchange Message channel",
        "tests_aspect": "PyPI, aio-pika (async RabbitMQ, hyphenated)",
    },
    # =====================================================================
    # Category Z: TypeScript Advanced (10) — TS utilities & patterns
    # =====================================================================
    {
        "id": "ts-pattern",
        "library": "ts-pattern",
        "query": "match with when exhaustive select P",
        "tests_aspect": "npm, ts-pattern (pattern matching, hyphenated)",
    },
    {
        "id": "type-fest",
        "library": "type-fest",
        "query": "PartialDeep RequiredDeep SetRequired Simplify",
        "tests_aspect": "npm, type-fest (TS type helpers, hyphenated)",
    },
    {
        "id": "zx",
        "library": "zx",
        "query": "$ cd fetch echo question within",
        "tests_aspect": "npm, zx (Google shell scripts, ultra-short name)",
    },
    {
        "id": "oclif",
        "library": "oclif",
        "query": "Command Flags Args Plugin Hook run",
        "tests_aspect": "npm, oclif.io (CLI framework by Salesforce)",
    },
    {
        "id": "tsyringe",
        "library": "tsyringe",
        "query": "container injectable inject singleton scoped",
        "tests_aspect": "npm, tsyringe (DI container, unique name)",
    },
    {
        "id": "inversify",
        "library": "inversify",
        "query": "Container bind injectable inject kernel",
        "tests_aspect": "npm, inversify.io (IoC container)",
    },
    {
        "id": "ts-morph",
        "library": "ts-morph",
        "query": "Project SourceFile Node Type ClassDeclaration",
        "tests_aspect": "npm, ts-morph (TypeScript AST manipulation)",
    },
    {
        "id": "type-graphql",
        "library": "type-graphql",
        "query": "Resolver Query Mutation Field ObjectType",
        "tests_aspect": "npm, typegraphql.com (GraphQL with TS decorators)",
    },
    {
        "id": "neverthrow",
        "library": "neverthrow",
        "query": "ok err Result ResultAsync fromPromise",
        "tests_aspect": "npm, neverthrow (Result type for TS)",
    },
    {
        "id": "arktype",
        "library": "arktype",
        "query": "type scope morph narrow infer union",
        "tests_aspect": "npm, arktype.io (runtime TS validation)",
    },
    # =====================================================================
    # Category AA: Python Data & Workflow (10) — data processing, caching
    # =====================================================================
    {
        "id": "tenacity",
        "library": "tenacity",
        "query": "retry stop wait before after retry_if",
        "tests_aspect": "PyPI, tenacity (retry library, unique name)",
    },
    {
        "id": "diskcache",
        "library": "diskcache",
        "query": "Cache FanoutCache DiskCache memoize Deque",
        "tests_aspect": "PyPI, grantjenks.com/docs/diskcache (disk-based cache)",
    },
    {
        "id": "cachetools",
        "library": "cachetools",
        "query": "LRUCache TTLCache cached cachedmethod",
        "tests_aspect": "PyPI, cachetools (extensible cache, unique name)",
    },
    {
        "id": "joblib",
        "library": "joblib",
        "query": "Parallel delayed Memory dump load hash",
        "tests_aspect": "PyPI, joblib.readthedocs.io (lightweight pipelining)",
    },
    {
        "id": "dask",
        "library": "dask",
        "query": "dataframe array delayed compute scheduler",
        "tests_aspect": "PyPI, dask.org (parallel computing)",
    },
    {
        "id": "ray",
        "library": "ray",
        "query": "remote init get put task actor serve",
        "tests_aspect": "PyPI, ray.io (distributed computing, generic name)",
    },
    {
        "id": "prefect",
        "library": "prefect",
        "query": "flow task deployment schedule parameter",
        "tests_aspect": "PyPI, prefect.io (workflow orchestration)",
    },
    {
        "id": "airflow",
        "library": "apache-airflow",
        "query": "DAG operator task sensor trigger schedule",
        "tests_aspect": "PyPI, airflow.apache.org (workflow scheduler)",
    },
    {
        "id": "dagster",
        "library": "dagster",
        "query": "asset op job schedule sensor io_manager",
        "tests_aspect": "PyPI, dagster.io (data orchestration, unique name)",
    },
    {
        "id": "luigi",
        "library": "luigi",
        "query": "Task Target requires output run Parameter",
        "tests_aspect": "PyPI, luigi (Spotify workflow, unique name)",
    },
    # =====================================================================
    # Category AB: Rust Ecosystem (10) — error handling, async, parsing
    # =====================================================================
    {
        "id": "anyhow",
        "library": "anyhow",
        "query": "Result Context Error bail ensure anyhow!",
        "tests_aspect": "crates.io, anyhow (error handling, unique name)",
    },
    {
        "id": "thiserror",
        "library": "thiserror",
        "query": "Error derive from source transparent display",
        "tests_aspect": "crates.io, thiserror (derive Error, unique name)",
    },
    {
        "id": "tracing-rs",
        "library": "tracing",
        "query": "span event instrument subscriber Layer",
        "tests_aspect": "crates.io, tracing-rs (instrumentation, generic name collision npm)",
    },
    {
        "id": "rayon",
        "library": "rayon",
        "query": "par_iter into_par_iter join scope ThreadPool",
        "tests_aspect": "crates.io, rayon (data parallelism, unique name)",
    },
    {
        "id": "regex-rust",
        "library": "regex",
        "query": "Regex captures find replace is_match",
        "tests_aspect": "crates.io, regex (ultra-generic name, npm collision)",
    },
    {
        "id": "hyper-rs",
        "library": "hyper",
        "query": "Client Server Request Response Body service",
        "tests_aspect": "crates.io, hyper.rs (HTTP library, npm collision)",
    },
    {
        "id": "tonic",
        "library": "tonic",
        "query": "Server Request Response Channel transport codec",
        "tests_aspect": "crates.io, tonic (gRPC framework, generic name)",
    },
    {
        "id": "prost",
        "library": "prost",
        "query": "Message encode decode prost_build Service",
        "tests_aspect": "crates.io, prost (Protocol Buffers, unique name)",
    },
    {
        "id": "tower",
        "library": "tower",
        "query": "Service Layer ServiceBuilder timeout retry",
        "tests_aspect": "crates.io, tower-rs (middleware abstractions, generic name)",
    },
    {
        "id": "nom",
        "library": "nom",
        "query": "tag take_while separated_list IResult many0",
        "tests_aspect": "crates.io, nom (parser combinators, ultra-short name)",
    },
    # =====================================================================
    # Category AC: Go Packages (10) — popular Go ecosystem tools
    # =====================================================================
    {
        "id": "cobra",
        "library": "cobra",
        "query": "Command Args Flags PersistentFlags RunE",
        "tests_aspect": "Go, cobra.dev (CLI framework, generic name)",
    },
    {
        "id": "viper",
        "library": "viper",
        "query": "SetConfigFile ReadInConfig Get Set BindPFlag",
        "tests_aspect": "Go, viper (config management, generic name collision npm)",
    },
    {
        "id": "zap",
        "library": "zap",
        "query": "Logger Sugar NewProduction Field Info Error",
        "tests_aspect": "Go, uber-go/zap (structured logging, generic name)",
    },
    {
        "id": "gorm",
        "library": "gorm",
        "query": "Model Create Find Where Preload AutoMigrate",
        "tests_aspect": "Go, gorm.io (ORM, unique name)",
    },
    {
        "id": "fx",
        "library": "fx",
        "query": "Provide Invoke Module New Supply Lifecycle",
        "tests_aspect": "Go, uber-go/fx (DI framework, ultra-short name collision npm)",
    },
    {
        "id": "wire",
        "library": "wire",
        "query": "Injector Provider Set Bind Value NewSet",
        "tests_aspect": "Go, google/wire (compile-time DI, generic name)",
    },
    {
        "id": "testify",
        "library": "testify",
        "query": "assert require suite mock Equal NotNil",
        "tests_aspect": "Go, testify (test toolkit, generic name)",
    },
    {
        "id": "mockery-go",
        "library": "mockery",
        "query": "mock generate interface expectations Return",
        "tests_aspect": "Go, mockery (mock generator, generic name collision npm)",
    },
    {
        "id": "air",
        "library": "air",
        "query": "live reload .air.toml build cmd tmp",
        "tests_aspect": "Go, air (hot reload, ultra-generic name collision)",
    },
    {
        "id": "gorilla-mux",
        "library": "gorilla/mux",
        "query": "Router HandleFunc PathPrefix Vars Subrouter",
        "tests_aspect": "Go, gorilla/mux (HTTP router, slash in name)",
    },
    # =====================================================================
    # Category AD: Mobile & Desktop (10) — cross-platform frameworks
    # =====================================================================
    {
        "id": "react-native",
        "library": "react-native",
        "query": "View Text StyleSheet FlatList navigation",
        "tests_aspect": "npm, reactnative.dev (mobile framework, hyphenated)",
    },
    {
        "id": "expo",
        "library": "expo",
        "query": "router config plugins assets SDK modules",
        "tests_aspect": "npm, docs.expo.dev (React Native platform)",
    },
    {
        "id": "capacitor",
        "library": "@capacitor/core",
        "query": "Plugins registerPlugin WebPlugin Capacitor bridge",
        "tests_aspect": "scoped npm, capacitorjs.com (mobile runtime)",
    },
    {
        "id": "electron",
        "library": "electron",
        "query": "BrowserWindow ipcMain ipcRenderer app menu",
        "tests_aspect": "npm, electronjs.org (desktop framework)",
    },
    {
        "id": "neutralinojs",
        "library": "@aspect/neutralino",
        "query": "app os filesystem window events computer",
        "tests_aspect": "npm, neutralino.js.org (lightweight desktop alt)",
    },
    {
        "id": "wails-go",
        "library": "wails",
        "query": "Application Window Bind Events menu dialog",
        "tests_aspect": "Go, wails.io (Go desktop framework)",
    },
    {
        "id": "fyne-go",
        "library": "fyne",
        "query": "App Window Canvas Widget Container Entry",
        "tests_aspect": "Go, fyne.io (Go GUI toolkit)",
    },
    {
        "id": "kivy",
        "library": "kivy",
        "query": "App Widget Builder BoxLayout Button Label",
        "tests_aspect": "PyPI, kivy.org (Python GUI framework)",
    },
    {
        "id": "dearpygui",
        "library": "dearpygui",
        "query": "create_viewport add_window add_button callback",
        "tests_aspect": "PyPI, dearpygui.readthedocs.io (Python GUI, unique name)",
    },
    {
        "id": "toga",
        "library": "toga",
        "query": "App MainWindow Box Button TextInput handler",
        "tests_aspect": "PyPI, toga.readthedocs.io (Python native UI, BeeWare)",
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
