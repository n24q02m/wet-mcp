## [2.1.2](https://github.com/n24q02m/wet-mcp/compare/v2.1.1...v2.1.2) (2026-02-04)


### Bug Fixes

* **searxng:** robust connection fix ([140eecb](https://github.com/n24q02m/wet-mcp/commit/140eecb5ee064033df30b6ad62da708b990c4427))

## [2.1.1](https://github.com/n24q02m/wet-mcp/compare/v2.1.0...v2.1.1) (2026-02-04)


### Bug Fixes

* update tests and formatting ([17906f3](https://github.com/n24q02m/wet-mcp/commit/17906f3641b80ae2fa267923cadd9b0169e411fa))

# [2.1.0](https://github.com/n24q02m/wet-mcp/compare/v2.0.0...v2.1.0) (2026-02-04)


### Features

* enable LLM analysis for text files and enhance SearXNG container startup with port readiness checks. ([4fb3f4e](https://github.com/n24q02m/wet-mcp/commit/4fb3f4eb1dc6ed7fd47c29da7e824fc03b8eb146))

# [2.0.0](https://github.com/n24q02m/wet-mcp/compare/v1.3.0...v2.0.0) (2026-02-04)


### Features

* refactor API_KEYS format and add auto-detect capabilities ([77e277b](https://github.com/n24q02m/wet-mcp/commit/77e277b8989a692cd3ede287ba25f83f949d3f4b))


### BREAKING CHANGES

* API_KEYS now expects ENV_VAR:key format
e.g. GOOGLE_API_KEY:abc instead of gemini:abc

# [1.3.0](https://github.com/n24q02m/wet-mcp/compare/v1.2.1...v1.3.0) (2026-02-03)


### Features

* Enhance crawler with retries, user-agent, redirect following, and protocol-relative URL handling. ([ab1ecea](https://github.com/n24q02m/wet-mcp/commit/ab1ecead5ae0fbbd4e7f33cd6d82e0a6e2215ea2))

## [1.2.1](https://github.com/n24q02m/wet-mcp/compare/v1.2.0...v1.2.1) (2026-02-03)


### Bug Fixes

* silence Crawl4AI verbose output to prevent JSON parse errors ([62d5f92](https://github.com/n24q02m/wet-mcp/commit/62d5f92a1a398fef7e4c1c9bd88cb52e2c63a2e0))

# [1.2.0](https://github.com/n24q02m/wet-mcp/compare/v1.1.0...v1.2.0) (2026-02-03)


### Features

* integrate LiteLLM for media analysis (analyze tool) ([77003ce](https://github.com/n24q02m/wet-mcp/commit/77003ce43c3641a1d755398a03806826720a343c))

# [1.1.0](https://github.com/n24q02m/wet-mcp/compare/v1.0.0...v1.1.0) (2026-02-03)


### Features

* integrate LiteLLM for media analysis (analyze tool) ([fe4d365](https://github.com/n24q02m/wet-mcp/commit/fe4d36571f6d2104f989e60178aac0e01d225002))

# 1.0.0 (2026-02-03)


### Features

* add initial project documentation including README, developer handbook, and agent context files ([f39cfab](https://github.com/n24q02m/wet-mcp/commit/f39cfabc2ccea02678a39acac9812c8c35832fe9))
* Establish initial project structure with SearXNG integration, Docker management, and CI/CD. ([57fcc33](https://github.com/n24q02m/wet-mcp/commit/57fcc330e94b4590955458b727999b81ca3cf39a))
