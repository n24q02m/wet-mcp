## 2025-02-18 - Hardcoded Secrets in Configuration Templates
**Vulnerability:** A hardcoded `secret_key` ("wet-mcp-internal-secret") was found in `searxng_settings.yml`, used by the embedded SearXNG instance.
**Learning:** Configuration templates often ship with default/example secrets. If these are not replaced at runtime, every instance shares the same secret, enabling session hijacking or forgery.
**Prevention:** Use placeholders (e.g., `REPLACE_WITH_REAL_SECRET`) in templates and generate cryptographically secure random values (e.g., `secrets.token_hex`) during application startup/initialization to replace them.
