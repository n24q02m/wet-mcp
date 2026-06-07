import os

def fix_file(path):
    with open(path, 'r') as f:
        content = f.read()

    # My previous replacement failed because of the leading r
    content = content.replace('r"\\`search\\`"', '"`search`"')
    content = content.replace('r"\\`extract\\`"', '"`extract`"')

    # Let's try matching with the exact content from sed output
    content = content.replace('r"\\`search\\` FINDS information', '"`search` FINDS information')
    content = content.replace('r"\\`extract\\` tool instead."', '"`extract` tool instead."')

    with open(path, 'w') as f:
        f.write(content)

fix_file('src/wet_mcp/server.py')
