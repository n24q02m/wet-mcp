## 2026-07-06 - Prevent Path Hijacking in Subprocess

**Vulnerability:** `subprocess.run` was called with a partial executable path `["gh", ...]`, exposing a potential path hijacking vulnerability (CWE-426 / S607). An attacker could place a malicious executable named `gh` in a directory higher in the `PATH` hierarchy (or the working directory on Windows) to execute arbitrary code.
**Learning:** This existed because the command name was supplied as a literal string assuming the OS would correctly resolve it to the globally installed GitHub CLI, overlooking the risk of localized path hijacking, especially in cross-platform tooling.
**Prevention:** Always use `shutil.which("executable_name")` to resolve the absolute path to the binary before passing it to `subprocess.run()`, and gracefully handle cases where the executable is missing.
