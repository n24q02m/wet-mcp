## [2.1.4-beta.4](https://github.com/n24q02m/wet-mcp/compare/v2.1.4-beta.3...v2.1.4-beta.4) (2026-02-05)


### Bug Fixes

* **cd:** use dry-run check to prevent workflow failure when no release needed ([e9686fe](https://github.com/n24q02m/wet-mcp/commit/e9686fe6115cd360aa9842148bd03c80c5c70a03))

## [2.3.0-beta](https://github.com/n24q02m/wet-mcp/compare/v2.2.0...v2.3.0-beta) (2026-02-09)


### Features

* add media analysis action and enhance SearXNG installation robustness. ([27dfa89](https://github.com/n24q02m/wet-mcp/commit/27dfa8918c67d6b6e3d5f1a649cb9521529dcae9))

## [2.2.0](https://github.com/n24q02m/wet-mcp/compare/v2.1.3...v2.2.0) (2026-02-08)


### Features

* promote dev to main (v3.1.0-beta.4) ([#17](https://github.com/n24q02m/wet-mcp/issues/17)) ([fd54513](https://github.com/n24q02m/wet-mcp/commit/fd545134a2cc338051c0e2dc4dfc8c91d5a00d16))

## [3.1.0-beta.4](https://github.com/n24q02m/wet-mcp/compare/v3.1.0-beta.3...v3.1.0-beta.4) (2026-02-08)


### Features

* add tool timeout setting and improve SearXNG compatibility on Windows ([2f42fb7](https://github.com/n24q02m/wet-mcp/commit/2f42fb72cf0fffe4c00607dfc9b946aa4da63170))

## [3.1.0-beta.3](https://github.com/n24q02m/wet-mcp/compare/v3.1.0-beta.2...v3.1.0-beta.3) (2026-02-08)


### Features

* implement version patching for SearXNG installation from zip archive ([18e678a](https://github.com/n24q02m/wet-mcp/commit/18e678a504f4fe091a933fded9665682bcdb5288))

## [3.1.0-beta.2](https://github.com/n24q02m/wet-mcp/compare/v3.1.0-beta.1...v3.1.0-beta.2) (2026-02-08)


### Bug Fixes

* add git installation in Dockerfile for SearXNG build system ([9c850ad](https://github.com/n24q02m/wet-mcp/commit/9c850adb54de66de42b7c49aa05b03fdc807be6c))

## [3.1.0-beta.1](https://github.com/n24q02m/wet-mcp/compare/v3.1.0-beta...v3.1.0-beta.1) (2026-02-08)


### Bug Fixes

* update pip commands to use uv for SearXNG and Playwright installation ([566cfde](https://github.com/n24q02m/wet-mcp/commit/566cfdeacd4cee30681c1b2d954319be1e4e5287))

## [3.1.0-beta](https://github.com/n24q02m/wet-mcp/compare/v3.0.1-beta...v3.1.0-beta) (2026-02-08)


### Features

* transition from Docker-based SearXNG to embedded subprocess management ([b4b468e](https://github.com/n24q02m/wet-mcp/commit/b4b468ee600db9d5f1c674424dda04e4404d8a48))
* update CI configuration and add pytest hook to pre-commit ([543d2e4](https://github.com/n24q02m/wet-mcp/commit/543d2e42f33b4d21190bb195682f885bb82800b9))

## [3.0.1-beta](https://github.com/n24q02m/wet-mcp/compare/v3.0.0...v3.0.1-beta) (2026-02-06)


### Bug Fixes

* add prerelease versioning strategy to beta config ([7e8e87b](https://github.com/n24q02m/wet-mcp/commit/7e8e87bdbb67a7da97875fe4757ff319c49c57db))

## [3.0.0](https://github.com/n24q02m/wet-mcp/compare/v2.1.4...v3.0.0) (2026-02-06)


### ⚠ BREAKING CHANGES

* API_KEYS now expects ENV_VAR:key format e.g. GOOGLE_API_KEY:abc instead of gemini:abc

### Features

* add development and production rulesets, update CI/CD workflows, and enhance project dependencies ([34da1e8](https://github.com/n24q02m/wet-mcp/commit/34da1e84af56ea68bac2e6253a587f81de85e5c0))
* add initial project documentation including README, developer handbook, and agent context files ([f39cfab](https://github.com/n24q02m/wet-mcp/commit/f39cfabc2ccea02678a39acac9812c8c35832fe9))
* enable LLM analysis for text files and enhance SearXNG container startup with port readiness checks. ([4fb3f4e](https://github.com/n24q02m/wet-mcp/commit/4fb3f4eb1dc6ed7fd47c29da7e824fc03b8eb146))
* Enhance crawler with retries, user-agent, redirect following, and protocol-relative URL handling. ([ab1ecea](https://github.com/n24q02m/wet-mcp/commit/ab1ecead5ae0fbbd4e7f33cd6d82e0a6e2215ea2))
* Establish initial project structure with SearXNG integration, Docker management, and CI/CD. ([57fcc33](https://github.com/n24q02m/wet-mcp/commit/57fcc330e94b4590955458b727999b81ca3cf39a))
* integrate LiteLLM for media analysis (analyze tool) ([77003ce](https://github.com/n24q02m/wet-mcp/commit/77003ce43c3641a1d755398a03806826720a343c))
* integrate LiteLLM for media analysis (analyze tool) ([fe4d365](https://github.com/n24q02m/wet-mcp/commit/fe4d36571f6d2104f989e60178aac0e01d225002))
* refactor API_KEYS format and add auto-detect capabilities ([77e277b](https://github.com/n24q02m/wet-mcp/commit/77e277b8989a692cd3ede287ba25f83f949d3f4b))


### Bug Fixes

* **cd:** checkout main branch for PR merge release ([5247100](https://github.com/n24q02m/wet-mcp/commit/524710028b2b25e6dff0393a0ace067abffc3054))
* **cd:** use dry-run check to prevent workflow failure when no release needed ([e9686fe](https://github.com/n24q02m/wet-mcp/commit/e9686fe6115cd360aa9842148bd03c80c5c70a03))
* **searxng:** robust connection fix ([140eecb](https://github.com/n24q02m/wet-mcp/commit/140eecb5ee064033df30b6ad62da708b990c4427))
* **server:** remove url cache to ensure auto-restart ([36f44d2](https://github.com/n24q02m/wet-mcp/commit/36f44d23b624a2422ef18597b4d855aea07de7b5))
* silence Crawl4AI verbose output to prevent JSON parse errors ([62d5f92](https://github.com/n24q02m/wet-mcp/commit/62d5f92a1a398fef7e4c1c9bd88cb52e2c63a2e0))
* **tests:** update version test to validate semantic versioning format ([768b82d](https://github.com/n24q02m/wet-mcp/commit/768b82de838e9c11e4087276611d4c49e1100a9e))
* trigger cd ([b825a4c](https://github.com/n24q02m/wet-mcp/commit/b825a4c63ce521c6e4e3fcf657ff088995e3c6be))
* update tests and formatting ([17906f3](https://github.com/n24q02m/wet-mcp/commit/17906f3641b80ae2fa267923cadd9b0169e411fa))


### Performance Improvements

* apply async optimizations from merged PRs ([36b3084](https://github.com/n24q02m/wet-mcp/commit/36b3084f6846763b7f06f771fe2754baf14803bf))


### Documentation

* chuẩn hóa repo cho public opensource ([0214974](https://github.com/n24q02m/wet-mcp/commit/021497451fa744ef864214d39be82095555f6bb8))

## [2.1.4-beta.3](https://github.com/n24q02m/wet-mcp/compare/v2.1.4-beta.2...v2.1.4-beta.3) (2026-02-05)


### Bug Fixes

* **cd:** checkout main branch for PR merge release ([5247100](https://github.com/n24q02m/wet-mcp/commit/524710028b2b25e6dff0393a0ace067abffc3054))

## [2.1.4-beta.2](https://github.com/n24q02m/wet-mcp/compare/v2.1.4-beta.1...v2.1.4-beta.2) (2026-02-05)


### Bug Fixes

* trigger cd ([b825a4c](https://github.com/n24q02m/wet-mcp/commit/b825a4c63ce521c6e4e3fcf657ff088995e3c6be))

## [2.1.4-beta.1](https://github.com/n24q02m/wet-mcp/compare/v2.1.3...v2.1.4-beta.1) (2026-02-05)


### Performance Improvements

* apply async optimizations from merged PRs ([36b3084](https://github.com/n24q02m/wet-mcp/commit/36b3084f6846763b7f06f771fe2754baf14803bf))

## [2.1.3](https://github.com/n24q02m/wet-mcp/compare/v2.1.2...v2.1.3) (2026-02-04)


### Bug Fixes

* **server:** remove url cache to ensure auto-restart ([36f44d2](https://github.com/n24q02m/wet-mcp/commit/36f44d23b624a2422ef18597b4d855aea07de7b5))

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
