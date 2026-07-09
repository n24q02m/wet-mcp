## 2025-02-14 - Prevent Path Hijacking with Subprocess

**Vulnerability:** The code in `src/wet_mcp/server.py` ran an external process using a partial executable name `subprocess.run(["gh", "auth", "token"])`, which relies on `PATH` resolution during execution and exposes the application to path hijacking. This was flagged by Bandit and Ruff (S607).
**Learning:** Checking for existence via `shutil.which()` and then relying on `subprocess.run()`'s internal path resolution is prone to race conditions and potential security issues, since they could resolve to different executables.
**Prevention:** Always use the absolute path of the executable by storing the result of `shutil.which()` and passing it into `subprocess.run()` (e.g. `path = shutil.which("gh"); subprocess.run([path, ...])`).
