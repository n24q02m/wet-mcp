## 2026-07-19 - Configurable Host Binding
**Vulnerability:** The server hardcoded a bind to `0.0.0.0` in remote multi-user mode, which is flagged by Bandit as a B104 issue because it binds to all interfaces without flexibility.
**Learning:** While binding to all interfaces is often necessary in containerized/remote deployments, hardcoding it removes the user's ability to restrict the server to specific network interfaces (e.g., internal VPN or specific subnets) for defense-in-depth.
**Prevention:** Always use environment variables (e.g., `os.environ.get("MCP_HOST", "0.0.0.0")`) for network bindings rather than hardcoded strings, and explicitly comment `# nosec B104` when the default is intentionally permissive.
