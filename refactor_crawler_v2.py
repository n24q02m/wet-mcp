import sys
import re

file_path = "src/wet_mcp/sources/crawler.py"
with open(file_path, "r") as f:
    content = f.read()

# Update _fetch_media_resource to return (response, target_url)
fetch_old = r"async def _fetch_media_resource\((.*?)\) -> httpx\.Response:(.*?)return response"
fetch_new = r"async def _fetch_media_resource(\1) -> tuple[httpx.Response, str]:\2return response, target_url"
content = re.sub(fetch_old, fetch_new, content, flags=re.DOTALL)

# Update _download_one to handle the tuple
download_old = r"response = await _fetch_media_resource\(url, client\)\n                filename = _get_media_filename\(\n                    str\(response\.url\), response\.headers\.get\(\"content-type\"\)\n                \)"
download_new = r"response, final_url = await _fetch_media_resource(url, client)\n                filename = _get_media_filename(\n                    final_url, response.headers.get(\"content-type\")\n                )"
content = re.sub(download_old, download_new, content)

with open(file_path, "w") as f:
    f.write(content)
print("Successfully updated refactor")
