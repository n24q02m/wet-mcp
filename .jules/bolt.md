## 2026-03-16 - [Fix too many arguments in extract tool]
**Code Health:** Fixed `PLR0913` (Too many arguments in function definition) for the `extract` tool.
**Learning:** When dealing with `@mcp.tool` decorated functions, modifying the function signature (e.g., grouping arguments into a dictionary or using `**kwargs`) will break the JSON Schema generated for the tool. The most correct and pragmatic approach is to suppress the linter warning using `# noqa: PLR0913` to preserve the tool's public contract.
**Prevention:** Avoid refactoring MCP tool signatures solely to satisfy linter rules about argument counts. Suppress the warning if the arguments are necessary for the tool's schema.
