import sys

with open('src/wet_mcp/db.py', 'r') as f:
    content = f.read()

with open('search_patch.txt', 'r') as f:
    patch = f.read()

search_part = patch.split('<<<<<<< SEARCH')[1].split('=======')[0].strip()
replace_part = patch.split('=======')[1].split('>>>>>>> REPLACE')[0].strip()

# Find the exact match. Note: indentation might be tricky.
# The search_part starts with '    def search('
# I will try to find it in the content.

if search_part in content:
    new_content = content.replace(search_part, replace_part)
    with open('src/wet_mcp/db.py', 'w') as f:
        f.write(new_content)
    print("Successfully patched")
else:
    print("Could not find search_part")
    # Debug: print first 50 chars of search_part
    print(f"Start of search_part: {repr(search_part[:50])}")
