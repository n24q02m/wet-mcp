import re

content = "# Docs\n\nContent.\n\nInitializing search\n\nToggle navigation"

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

print("Opt:", repr(opt(content)))
