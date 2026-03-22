import pytest
from wet_mcp.sources.docs import _clean_doc_content

def test_removes_footer():
    content = "# Docs\n\nMain content.\n\nBuilt with MkDocs"
    result = _clean_doc_content(content)
    assert "Built with MkDocs" not in result

def test_removes_mkdocs_ui():
    content = "# Docs\n\nContent.\n\nInitializing search\n\nToggle navigation"
    result = _clean_doc_content(content)
    assert "Initializing search" not in result
    assert "Toggle navigation" not in result

if __name__ == "__main__":
    pytest.main(["-q", __file__])
