with open("tests/test_security_path_traversal.py") as f:
    content = f.read()

content = content.replace(
    'patch("httpx.AsyncClient"', 'patch("wet_mcp.sources.crawler.httpx.AsyncClient"'
)

with open("tests/test_security_path_traversal.py", "w") as f:
    f.write(content)
