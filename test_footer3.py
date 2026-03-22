from wet_mcp.sources.docs import _clean_doc_content
content = "# Docs\n\nMain content.\n\nBuilt with MkDocs"
print(repr(_clean_doc_content(content)))
