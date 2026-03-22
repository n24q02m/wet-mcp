import re
_BADGE_RE = re.compile(
    r"!\[.*?\]\(https?://(?:img\.shields\.io|badge\.|badges\.|github\.com/.*?/badge).*?\)",
    re.IGNORECASE,
)
_ADMONITION_RE = re.compile(
    r"^!!!?\s+(?:note|tip|warning|info|danger|example|quote|abstract|"
    r"success|failure|bug|todo|question|hint|caution|attention|important|seealso)"
    r"(?:\s+\"[^\"]*\")?\s*\n(?:(?:\s{4}|\t).*\n)*",
    re.MULTILINE | re.IGNORECASE,
)
_MKDOCSTRINGS_RE = re.compile(r"^:::.*$", re.MULTILINE)
_HTML_TAG_RE = re.compile(
    r"<(?!code|pre)[a-z][^>]*>|</(?!code|pre)[a-z][^>]*>", re.IGNORECASE
)
_TOC_LINK_RE = re.compile(r"^\s*[-*]\s*\[.*?\]\(#[^)]*\)\s*$", re.MULTILINE)
_FRONTMATTER_RE = re.compile(r"\A---\s*\n.*?\n---\s*\n", re.DOTALL)

_NAV_LINE_PAT = (
    r"^[ \t]*[-*][ \t]+(?:\[[^\]]*\][ \t]*)?\[[^\]]*\]\(https?://[^\)]*\)[ \t]*(?:\n|$)"
    r"|^[ \t]*\d+\.[ \t]+\[[^\]]*\]\(https?://[^\)]*\)[ \t]*(?:\n|$)"
)
_NAV_BLOCK_MIN_LINES = 8
_NAV_BLOCK_RE = re.compile(f"(?:{_NAV_LINE_PAT}){{{_NAV_BLOCK_MIN_LINES},}}", re.MULTILINE)

def _strip_nav_blocks(content: str) -> str:
    if not content:
        return content
    res = _NAV_BLOCK_RE.sub("", content)
    return "\n".join(res.splitlines())

def _strip_nav_heading_blocks(content: str) -> str:
    return content

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

def _clean_doc_content(content: str) -> str:
    content = _FRONTMATTER_RE.sub("", content)
    content = _BADGE_RE.sub("", content)
    content = _ADMONITION_RE.sub("", content)
    content = _MKDOCSTRINGS_RE.sub("", content)
    content = _HTML_TAG_RE.sub("", content)
    content = _TOC_LINK_RE.sub("", content)
    content = _strip_nav_blocks(content)
    content = _strip_nav_heading_blocks(content)
    res = _COMBINED_NOISE_MULTILINE_RE.sub("", content)
    return "\n".join(res.splitlines())

content = "# Docs\n\nMain content.\n\nBuilt with MkDocs"
print("Result:")
print(repr(_clean_doc_content(content)))

content2 = "# Docs\n\nContent.\n\nInitializing search\n\nToggle navigation"
print(repr(_clean_doc_content(content2)))
