import re

_LINK_LINE_RE = re.compile(r"^\s*[-*]?\s*\[.+?\]\(.+?\)\s*$|^\s*https?://\S+\s*$")

test_cases = [
    "   - [my link](http://google.com)",
    "  [link](/local/path)",
    " * [another link](https://x.com) ",
    "http://google.com ",
    "  https://example.com   ",
]

for tc in test_cases:
    assert _LINK_LINE_RE.match(tc)

    assert '[' in tc or 'http' in tc, f"Failed fast-path check for {tc}"

print("All assertions passed!")
