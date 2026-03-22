content = "# Docs\n\nMain content.\n\nBuilt with MkDocs"

def orig(content):
    lines = content.splitlines()
    cleaned = []
    import re
    _FOOTER_RE = re.compile(
        r"^\s*(?:"
        r"Built with|Powered by|Made with|Generated (?:by|with)|"
        r"Copyright\s*(?:\u00a9|\(c\))|\u00a9\s*\d{4}|"
        r"All [Rr]ights [Rr]eserved"
        r")",
        re.IGNORECASE,
    )
    for line in lines:
        stripped = line.strip()
        if not stripped:
            cleaned.append(line)
            continue
        if _FOOTER_RE.match(stripped):
            continue
        cleaned.append(line)
    return "\n".join(cleaned)

print("Orig:", repr(orig(content)))
