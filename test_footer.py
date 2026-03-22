import re
from wet_mcp.sources.docs import _clean_doc_content

content = "# Docs\n\nMain content.\n\nBuilt with MkDocs"
result = _clean_doc_content(content)
print(repr(result))
