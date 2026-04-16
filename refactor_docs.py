import sys
from dataclasses import dataclass
from typing import Any

def refactor():
    with open('src/wet_mcp/sources/docs.py', 'r') as f:
        lines = f.readlines()

    target_line = -1
    for i, line in enumerate(lines):
        if 'async def fetch_docs_pages' in line:
            target_line = i
            break

    if target_line == -1:
        print("Could not find fetch_docs_pages")
        sys.exit(1)

    new_lines = lines[:target_line]
    new_lines.append('@dataclass\n')
    new_lines.append('class DocsCrawlContext:\n')
    new_lines.append('    """State and configuration for a documentation crawl."""\n')
    new_lines.append('\n')
    new_lines.append('    docs_url: str\n')
    new_lines.append('    docs_parsed: Any\n')
    new_lines.append('    query: str\n')
    new_lines.append('    max_pages: int\n')
    new_lines.append('    seen_urls: set[str]\n')
    new_lines.append('    pending_urls: list[str]\n')
    new_lines.append('    pages: list[dict]\n')
    new_lines.append('    version_prefix: str = ""\n')
    new_lines.append('    is_github: bool = False\n')
    new_lines.append('    gh_path_prefix: str = ""\n')
    new_lines.append('    blocked_count: int = 0\n')
    new_lines.append('\n')
    new_lines.append('\n')
    new_lines.append('_GH_SKIP_PATHS = {\n')
    new_lines.append('    "features",\n')
    new_lines.append('    "enterprise",\n')
    new_lines.append('    "copilot",\n')
    new_lines.append('    "marketplace",\n')
    new_lines.append('    "security",\n')
    new_lines.append('    "sponsors",\n')
    new_lines.append('    "login",\n')
    new_lines.append('    "signup",\n')
    new_lines.append('    "about",\n')
    new_lines.append('    "pricing",\n')
    new_lines.append('    "customer-stories",\n')
    new_lines.append('    "why-github",\n')
    new_lines.append('}\n')
    new_lines.append('\n')
    new_lines.append('_SKIP_URL_PATTERNS = (\n')
    new_lines.append('    "/genindex",\n')
    new_lines.append('    "/searchindex",\n')
    new_lines.append('    "/modindex",\n')
    new_lines.append('    "/_modules/",\n')
    new_lines.append('    "/_sources/",\n')
    new_lines.append('    "/blog/",\n')
    new_lines.append('    "/changelog",\n')
    new_lines.append('    "/releases",\n')
    new_lines.append(')\n')
    new_lines.append('\n\n')
    new_lines.extend(lines[target_line:])

    with open('src/wet_mcp/sources/docs.py', 'w') as f:
        f.writelines(new_lines)

if __name__ == "__main__":
    refactor()
