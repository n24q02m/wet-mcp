import re

content = "# Docs\n\nMain content.\n\nBuilt with MkDocs"

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
    # What if we just substitute with ""? Wait, if we substitute with "", the newline after the line is ALSO consumed,
    # so we drop the whole line.
    res = _COMBINED_NOISE_MULTILINE_RE.sub("", content)
    # The original loop preserved the empty line *before* "Built with MkDocs" because it did not strip empty lines.
    # The original returned: "# Docs\n\nMain content.\n"
    # Why?
    # lines = ["# Docs", "", "Main content.", "", "Built with MkDocs"]
    # line="" -> append ""
    # line="Built with MkDocs" -> match, continue.
    # cleaned = ["# Docs", "", "Main content.", ""]
    # "\n".join(cleaned) = "# Docs\n\nMain content.\n"
    return "\n".join(res.splitlines())

print("Opt:", repr(opt(content)))
