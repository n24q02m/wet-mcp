import sys
from pathlib import Path

file_path = Path("src/wet_mcp/server.py")
content = file_path.read_text()

# Part 1: Consolidate imports
old_imports = """from wet_mcp.sources.crawler import (
    crawl as _crawl,
)
from wet_mcp.sources.crawler import (
    extract as _extract,
)
from wet_mcp.sources.crawler import (
    list_media,
)
from wet_mcp.sources.crawler import (
    sitemap as _sitemap,
)"""

new_imports = """from wet_mcp.sources.crawler import (
    crawl as _crawl,
    extract as _extract,
    list_media,
    shutdown_crawler,
    sitemap as _sitemap,
)"""

if old_imports not in content:
    print("Error: Could not find old imports block")
    sys.exit(1)

content = content.replace(old_imports, new_imports)

# Part 2: Remove local import
old_local_import = """    # Shut down the shared browser pool first (may take a few seconds)
    try:
        from wet_mcp.sources.crawler import shutdown_crawler

        await shutdown_crawler()"""

new_local_import = """    # Shut down the shared browser pool first (may take a few seconds)
    try:
        await shutdown_crawler()"""

if old_local_import not in content:
    print("Error: Could not find local import block")
    # Try with slightly different whitespace just in case
    print("Content around expected location:")
    # Find something close
    idx = content.find("shutdown_crawler")
    if idx != -1:
        print(content[idx-100:idx+100])
    sys.exit(1)

content = content.replace(old_local_import, new_local_import)

file_path.write_text(content)
print("Successfully modified src/wet_mcp/server.py")
