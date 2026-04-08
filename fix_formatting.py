import sys

with open("tests/test_docs_coverage.py", "r") as f:
    lines = f.readlines()

start_line = -1
end_line = -1
for i, line in enumerate(lines):
    if "from wet_mcp.sources.docs import (" in line:
        start_line = i + 1
    if start_line != -1 and ")" in line and end_line == -1:
        end_line = i
        break

if start_line != -1 and end_line != -1:
    import_lines = lines[start_line:end_line]
    # Remove whitespace and commas for sorting
    imports = []
    for l in import_lines:
        name = l.strip().rstrip(",")
        if name:
            imports.append(name)

    imports.sort()

    new_import_lines = ["    {},\n".format(name) for name in imports]
    lines[start_line:end_line] = new_import_lines

# Also ensure no trailing whitespace and exactly one newline at end
content = "".join(lines).rstrip() + "\n"

with open("tests/test_docs_coverage.py", "w") as f:
    f.write(content)
