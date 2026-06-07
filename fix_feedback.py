import os

def fix_file(path):
    with open(path, 'r') as f:
        content = f.read()

    # Remove unintended backslashes in backticks
    content = content.replace('r"\\`search\\`"', '"`search`"')
    content = content.replace('r"\\`extract\\`"', '"`extract`"')

    # Fix the path in main docstring (re-join it correctly)
    content = content.replace(
        'See ``~/projects/.superpower/mcp-core/specs/\n    2026-05-01-stdio-pure-http-multiuser.md``.',
        'See ``~/projects/.superpower/mcp-core/specs/2026-05-01-stdio-pure-http-multiuser.md``.'
    )

    with open(path, 'w') as f:
        f.write(content)

fix_file('src/wet_mcp/server.py')
