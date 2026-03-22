import re

content = "# Docs\n\nMain content.\n\nBuilt with MkDocs"

_FOOTER_RE = re.compile(
    r"^\s*(?:"
    r"Built with|Powered by|Made with|Generated (?:by|with)|"
    r"Copyright\s*(?:\u00a9|\(c\))|\u00a9\s*\d{4}|"
    r"All [Rr]ights [Rr]eserved"
    r")",
    re.IGNORECASE,
)

def orig(content):
    lines = content.splitlines()
    cleaned = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            cleaned.append(line)
            continue
        if _FOOTER_RE.match(stripped):
            continue
        cleaned.append(line)
    return "\n".join(cleaned)

print("orig:", repr(orig(content)))

_COMBINED_NOISE_MULTILINE_RE = re.compile(
    r"^[ \t]*(?:"
    r"(?:"
    r"\u2190 Previous|Next \u2192|Skip to (?:main )?content|"
    r"Table of [Cc]ontents|On this page|"
    r"Edit (?:this|on) (?:page|GitHub)|"
    r"Suggest (?:changes|edits)|"
    r"Was this (?:page|article) helpful\?|"
    r"\u2b50 Star (?:us|this)|"
    r"Built with|Powered by|Made with|Generated (?:by|with)|"
    r"Copyright[ \t]*(?:\u00a9|\(c\))|\u00a9[ \t]*\d{4}|"
    r"All [Rr]ights [Rr]eserved"
    r").*|"
    r"(?:Initializing search|Toggle (?:navigation|search)|Search|"
    r"Back to top|Share\b|Go to repository)[ \t]*"
    r")(?:\n|$)",
    re.IGNORECASE | re.MULTILINE
)

def opt(content):
    res = _COMBINED_NOISE_MULTILINE_RE.sub("", content)
    return "\n".join(res.splitlines())

print("opt:", repr(opt(content)))
