import os

with open("tests/test_docs_coverage.py", "r") as f:
    lines = f.readlines()

# 1. Handle imports
start_idx = -1
end_idx = -1
for i, line in enumerate(lines):
    if "from wet_mcp.sources.docs import (" in line:
        start_idx = i + 1
    if start_idx != -1 and ")" in line and end_idx == -1:
        end_idx = i
        break

if start_idx != -1 and end_idx != -1:
    imports = set()
    for i in range(start_idx, end_idx):
        name = lines[i].strip().rstrip(",")
        if name:
            imports.add(name)
    imports.add("chunk_llms_txt")
    sorted_imports = sorted(list(imports))
    new_lines = ["    {},\n".format(name) for name in sorted_imports]
    lines[start_idx:end_idx] = new_lines

# 2. Handle test function
test_code = """
# ---------------------------------------------------------------------------
# chunk_llms_txt
# ---------------------------------------------------------------------------


def test_chunk_llms_txt_delegation():
    \"\"\"chunk_llms_txt delegates to chunk_markdown with correct parameters.\"\"\"
    with patch(\"wet_mcp.sources.docs.chunk_markdown\") as mock_chunk:
        mock_chunk.return_value = [{\"content\": \"chunk1\"}]
        content = \"some content\"
        url = \"https://docs.test\"
        result = chunk_llms_txt(content, base_url=url)

        mock_chunk.assert_called_once_with(content, url=url, max_chunk_size=2000)
        assert result == [{\"content\": \"chunk1\"}]
"""

content = "".join(lines).rstrip()
if "def test_chunk_llms_txt_delegation():" not in content:
    content += test_code
content = content.rstrip() + "\n"

with open("tests/test_docs_coverage.py", "w") as f:
    f.write(content)
