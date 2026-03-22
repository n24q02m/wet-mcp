import re

content = "# Docs\n\nContent.\n\nInitializing search\n\nToggle navigation"

def orig(content):
    lines = content.splitlines()
    cleaned = []
    _MKDOCS_UI_RE = re.compile(
        r"^\s*(?:"
        r"Initializing search|Toggle (?:navigation|search)|Search"
        r"|Back to top|Share\b|Go to repository"
        r")\s*$",
        re.IGNORECASE,
    )
    for line in lines:
        stripped = line.strip()
        if not stripped:
            cleaned.append(line)
            continue
        if _MKDOCS_UI_RE.match(stripped):
            continue
        cleaned.append(line)
    return "\n".join(cleaned)

print("Orig:", repr(orig(content)))
