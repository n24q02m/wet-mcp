import sys
import re
from pathlib import Path

file_path = "src/wet_mcp/sources/crawler.py"
with open(file_path, "r") as f:
    content = f.read()

# Pattern for the old _download_one function
full_download_one_pattern = r"    async def _download_one\(url: str, client: httpx\.AsyncClient\) -> dict:.*?                return \{\n                    \"url\": url,\n                    \"error\": str\(e\),\n                \}"
full_download_one_match = re.search(full_download_one_pattern, content, re.DOTALL)

if full_download_one_match:
    full_new_download_one = """    async def _download_one(url: str, client: httpx.AsyncClient) -> dict:
        async with semaphore:
            try:
                response = await _fetch_media_resource(url, client)
                filename = _get_media_filename(
                    str(response.url), response.headers.get("content-type")
                )
                filepath = _resolve_safe_media_path(filename, output_path)

                # Write file in thread to avoid blocking event loop
                await asyncio.to_thread(filepath.write_bytes, response.content)

                return {
                    "url": url,
                    "path": str(filepath),
                    "size": len(response.content),
                }

            except Exception as e:
                logger.error(f"Error downloading {url}: {e}")
                return {
                    "url": url,
                    "error": str(e),
                }"""

    new_content = content.replace(full_download_one_match.group(0), full_new_download_one)
    with open(file_path, "w") as f:
        f.write(new_content)
    print("Successfully refactored _download_one")
else:
    print("Could not find _download_one to replace")
    sys.exit(1)
