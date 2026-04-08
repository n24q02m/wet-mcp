# ruff: noqa: E402, I001
import sys
from unittest.mock import MagicMock

# 1. Mock EVERYTHING before importing wet_mcp
mcp = MagicMock()
sys.modules["mcp"] = mcp
sys.modules["mcp.server"] = MagicMock()
sys.modules["mcp.server.fastmcp"] = MagicMock()
sys.modules["mcp.types"] = MagicMock()
sys.modules["loguru"] = MagicMock()
sys.modules["mcp_relay_core"] = MagicMock()
sys.modules["mcp_relay_core.relay"] = MagicMock()
sys.modules["n24q02m_web_core"] = MagicMock()
sys.modules["n24q02m_web_core.search"] = MagicMock()
sys.modules["n24q02m_web_core.search.runner"] = MagicMock()
sys.modules["wet_mcp.security"] = MagicMock()
sys.modules["cohere"] = MagicMock()
sys.modules["google"] = MagicMock()
sys.modules["google.genai"] = MagicMock()
sys.modules["openai"] = MagicMock()
sys.modules["sqlite_vec"] = MagicMock()
sys.modules["qwen3_embed"] = MagicMock()
sys.modules["markitdown"] = MagicMock()
sys.modules["jsonschema"] = MagicMock()
sys.modules["aiolimiter"] = MagicMock()
sys.modules["diskcache"] = MagicMock()
sys.modules["cryptography"] = MagicMock()
sys.modules["cryptography.fernet"] = MagicMock()
sys.modules["waitress"] = MagicMock()
sys.modules["pydantic"] = MagicMock()
sys.modules["pydantic_settings"] = MagicMock()
sys.modules["httpx"] = MagicMock()

# Mock wet_mcp.credential_state to avoid conftest error
cred_state = MagicMock()
sys.modules["wet_mcp.credential_state"] = cred_state

# Mock wet_mcp.sources.crawler to avoid conftest error
crawler = MagicMock()
sys.modules["wet_mcp.sources.crawler"] = crawler

# 2. Mock importlib.metadata.version BEFORE wet_mcp is imported
import importlib.metadata

original_version = importlib.metadata.version


def mock_version(name):
    if name == "wet-mcp":
        return "2.24.0"
    return original_version(name)


importlib.metadata.version = mock_version

# 3. Prevent __init__.py from importing everything
sys.modules["wet_mcp.__main__"] = MagicMock()
sys.modules["wet_mcp.server"] = MagicMock()

# 4. Import the function
from wet_mcp.sources.docs import chunk_markdown


def test_h1_resets_h2():
    """H1 should reset the H2 state for heading_path."""
    content = """# Title 1
## Section 1.1
Content 1.1
# Title 2
## Section 2.1
Content 2.1
"""
    chunks = chunk_markdown(content, min_chunk_size=1)

    assert chunks[0]["title"] == "Title 1"
    assert chunks[1]["title"] == "Section 1.1"
    assert chunks[1]["heading_path"] == "Title 1 > Section 1.1"
    assert chunks[2]["title"] == "Title 2"
    assert chunks[2]["heading_path"] == "Title 2"
    assert chunks[3]["title"] == "Section 2.1"
    assert chunks[3]["heading_path"] == "Title 2 > Section 2.1"


def test_h4_heading():
    """H4 headings should be recognized and used in heading_path."""
    content = """# H1
## H2
### H3
#### H4
Content under H4
"""
    chunks = chunk_markdown(content, max_chunk_size=200, min_chunk_size=1)
    assert len(chunks) == 2
    assert chunks[0]["title"] == "H1"
    assert chunks[1]["title"] == "H4"
    assert chunks[1]["heading_path"] == "H1 > H2 > H4"


def test_h3_flush_threshold():
    """H3 should flush only if current chunk is large enough (max_chunk_size // 2)."""
    max_size = 200
    # Case 1: Below threshold
    content_small = "## H2\n" + "a" * 50 + "\n### H3\n" + "b" * 50
    chunks_small = chunk_markdown(
        content_small, max_chunk_size=max_size, min_chunk_size=1
    )
    assert len(chunks_small) == 1
    assert chunks_small[0]["title"] == "H3"
    assert chunks_small[0]["heading_path"] == "H2 > H3"

    # Case 2: Above threshold
    content_large = "## H2\n" + "a" * 120 + "\n### H3\n" + "b" * 50
    chunks_large = chunk_markdown(
        content_large, max_chunk_size=max_size, min_chunk_size=1
    )
    assert len(chunks_large) == 2
    assert chunks_large[0]["title"] == "H2"
    assert chunks_large[1]["title"] == "H3"


def test_noise_cleaning_integration():
    """_clean_doc_content noise removal works within chunk_markdown."""
    content = """---
title: My Doc
---
# Title
![Badge](https://img.shields.io/badge/any)

## Section
Content
"""
    chunks = chunk_markdown(content, min_chunk_size=1)
    # The noise should be removed by _clean_doc_content
    for c in chunks:
        assert "---" not in c["content"]
        assert "shields.io" not in c["content"]


def test_empty_after_cleaning():
    """Should return empty list if all content is noise."""
    content = "![Badge](https://img.shields.io/badge/any-thing-blue)"
    chunks = chunk_markdown(content)
    assert chunks == []


def test_empty_content_variants():
    """Empty or whitespace-only strings."""
    assert chunk_markdown("") == []
    assert chunk_markdown("   \n\t  ") == []


if __name__ == "__main__":
    test_h1_resets_h2()
    test_h4_heading()
    test_h3_flush_threshold()
    test_noise_cleaning_integration()
    test_empty_after_cleaning()
    test_empty_content_variants()
    print("All detailed tests passed!")
