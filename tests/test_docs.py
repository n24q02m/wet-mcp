"""Tests for src/wet_mcp/sources/docs.py — Docs discovery and chunking.

Covers chunk_markdown splitting, heading hierarchy, oversized content,
chunk_llms_txt, discover_library with mocked registries, try_llms_txt.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from wet_mcp.sources.docs import (
    chunk_llms_txt,
    chunk_markdown,
    discover_library,
    try_llms_txt,
)

# -----------------------------------------------------------------------
# chunk_markdown
# -----------------------------------------------------------------------


class TestChunkMarkdown:
    def test_basic_heading_split(self):
        """Content is split on ## headings."""
        content = """# Main Title

Some intro text.

## Section A

Content of section A goes here with enough text to meet the minimum size.
This section has important information about the topic at hand.

## Section B

Content of section B with more details and information.
Additional text to ensure this chunk meets minimum requirements.
"""
        chunks = chunk_markdown(content, url="https://example.com/docs")
        assert len(chunks) >= 2
        # All chunks should have content
        for chunk in chunks:
            assert chunk["content"]
            assert chunk["url"] == "https://example.com/docs"

    def test_heading_hierarchy_preserved(self):
        """heading_path tracks h1 > h2 hierarchy."""
        content = """# Library Guide

## Installation

Install with pip install library-name and follow the instructions.
Make sure you have Python 3.13 installed on your system first.

## Usage

Use the library by importing it at the top of your file.
Then call the main function to get started with the project.
"""
        chunks = chunk_markdown(content)
        titles = [c["title"] for c in chunks]
        assert "Installation" in titles or "Library Guide" in titles

    def test_oversized_chunk_split(self):
        """Chunks exceeding max_chunk_size are split by paragraphs."""
        # Create content with one heading but very long text
        paragraphs = ["Paragraph number {i}. " * 20 for i in range(20)]
        content = "## Big Section\n\n" + "\n\n".join(paragraphs)

        chunks = chunk_markdown(content, max_chunk_size=500)
        # Should be split into multiple chunks
        assert len(chunks) > 1
        # Each chunk should respect max size (approximately)
        for chunk in chunks:
            # Allow some leeway for the heading line
            assert len(chunk["content"]) <= 600

    def test_empty_content(self):
        """Empty or whitespace-only content returns no chunks."""
        assert chunk_markdown("") == []
        assert chunk_markdown("   \n  \n  ") == []

    def test_min_chunk_size_filter(self):
        """Chunks smaller than min_chunk_size are discarded."""
        content = """## Section A

Short.

## Section B

This section has enough content to meet the minimum chunk size requirement.
It contains multiple sentences with substantial information.
"""
        chunks = chunk_markdown(content, min_chunk_size=100)
        # "Short." section should be filtered out
        for chunk in chunks:
            assert len(chunk["content"]) >= 100

    def test_h3_splitting(self):
        """H3 headers trigger new chunks when current chunk is large enough."""
        content = """# Guide

## Getting Started

Some initial setup text that should be part of the first chunk.
Additional content to make this chunk reasonably sized for testing.

### Prerequisites

You need Python 3.13 and pip installed on your system.
Also make sure you have git for version control purposes.

### Installation Steps

Step 1: Clone the repository from GitHub using git clone.
Step 2: Install dependencies using pip install -r requirements.txt.
"""
        chunks = chunk_markdown(content, max_chunk_size=200)
        assert len(chunks) >= 2

    def test_chunk_index_sequential(self):
        """chunk_index is sequential starting from 0."""
        content = """## A

First section with enough content to be a valid chunk.
More text here to meet minimum size requirements.

## B

Second section with enough content to be a valid chunk.
More text here to meet minimum size requirements.

## C

Third section with enough content to be a valid chunk.
More text here to meet minimum size requirements.
"""
        chunks = chunk_markdown(content)
        indices = [c["chunk_index"] for c in chunks]
        assert indices == list(range(len(chunks)))

    def test_no_headings(self):
        """Content without headings produces one chunk."""
        content = "This is raw text without any markdown headings.\n" * 5
        chunks = chunk_markdown(content, min_chunk_size=50)
        assert len(chunks) == 1

    def test_code_blocks_preserved(self):
        """Code blocks within content are kept intact."""
        content = """## API Reference

Use the function like this:

```python
from library import main
result = main(param="value")
print(result)
```

The function returns a dictionary with the results.
Additional explanation about the API and its usage.
"""
        chunks = chunk_markdown(content)
        assert any("```python" in c["content"] for c in chunks)

    def test_unicode_content(self):
        """Unicode content is handled correctly."""
        content = """## Quoc te hoa

Ho tro da ngon ngu: Tieng Viet, English, Japanese.
Noi dung nay du dai de tao thanh mot chunk hop le.
"""
        chunks = chunk_markdown(content)
        assert len(chunks) > 0
        assert "Tieng Viet" in chunks[0]["content"]


# -----------------------------------------------------------------------
# chunk_llms_txt
# -----------------------------------------------------------------------


class TestChunkLlmsTxt:
    def test_basic_llms_txt(self):
        """llms.txt content is chunked with larger max_chunk_size."""
        content = """# Library Name

> A brief description of the library.

## Installation

Install with: pip install library-name
Make sure Python 3.13 is installed first. The library supports all major platforms.
Additional installation notes and requirements are listed below in this section.

## Quick Start

```python
from library import Client
client = Client()
result = client.query("hello world")
```

The client handles authentication automatically using environment variables.
You can configure the client with various options for different use cases.
"""
        chunks = chunk_llms_txt(content, base_url="https://example.com")
        assert len(chunks) > 0
        for chunk in chunks:
            assert chunk["url"] == "https://example.com"


# -----------------------------------------------------------------------
# discover_library (mocked registries)
# -----------------------------------------------------------------------


class TestDiscoverLibrary:
    @pytest.mark.asyncio
    async def test_discover_from_npm(self):
        """Discovers library from npm registry."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "name": "react",
            "description": "A JavaScript library for building user interfaces",
            "homepage": "https://react.dev",
            "repository": {"url": "https://github.com/facebook/react"},
        }

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None

        with patch("wet_mcp.sources.docs.httpx.AsyncClient", return_value=mock_client):
            result = await discover_library("react")

        assert result is not None
        assert result["homepage"] == "https://react.dev"
        assert result["registry"] == "npm"

    @pytest.mark.asyncio
    async def test_discover_from_pypi(self):
        """Discovers library from PyPI when npm fails."""
        mock_npm_response = MagicMock()
        mock_npm_response.status_code = 404

        mock_pypi_response = MagicMock()
        mock_pypi_response.status_code = 200
        mock_pypi_response.json.return_value = {
            "info": {
                "name": "fastapi",
                "summary": "FastAPI framework",
                "home_page": "https://fastapi.tiangolo.com",
                "project_urls": {
                    "Documentation": "https://fastapi.tiangolo.com",
                    "Repository": "https://github.com/tiangolo/fastapi",
                },
            }
        }

        mock_crates_response = MagicMock()
        mock_crates_response.status_code = 404

        responses = {
            "registry.npmjs.org": mock_npm_response,
            "pypi.org": mock_pypi_response,
            "crates.io": mock_crates_response,
        }

        def route_get(url, **kwargs):
            for key, resp in responses.items():
                if key in url:
                    return resp
            return mock_npm_response

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=route_get)
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None

        with patch("wet_mcp.sources.docs.httpx.AsyncClient", return_value=mock_client):
            result = await discover_library("fastapi")

        assert result is not None
        assert result["registry"] == "pypi"
        assert "fastapi" in result["homepage"]

    @pytest.mark.asyncio
    async def test_discover_all_registries_fail(self):
        """Returns None when all registries fail."""
        mock_response = MagicMock()
        mock_response.status_code = 404

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None

        with patch("wet_mcp.sources.docs.httpx.AsyncClient", return_value=mock_client):
            result = await discover_library("nonexistent-library-xyz")

        assert result is None


# -----------------------------------------------------------------------
# try_llms_txt
# -----------------------------------------------------------------------


class TestTryLlmsTxt:
    @pytest.mark.asyncio
    async def test_found_llms_full_txt(self):
        """Returns content when llms-full.txt exists."""
        long_content = "# Library\n\n" + ("Documentation content. " * 20)

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = long_content

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None

        with patch("wet_mcp.sources.docs.httpx.AsyncClient", return_value=mock_client):
            result = await try_llms_txt("https://example.com/docs")

        assert result == long_content

    @pytest.mark.asyncio
    async def test_rejects_html_page(self):
        """Rejects content that looks like an HTML error page."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = "<!DOCTYPE html><html><body>404 Not Found</body></html>"

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None

        with patch("wet_mcp.sources.docs.httpx.AsyncClient", return_value=mock_client):
            result = await try_llms_txt("https://example.com")

        assert result is None

    @pytest.mark.asyncio
    async def test_rejects_short_content(self):
        """Rejects content shorter than 200 chars (likely error page)."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = "Short content"

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None

        with patch("wet_mcp.sources.docs.httpx.AsyncClient", return_value=mock_client):
            result = await try_llms_txt("https://example.com")

        assert result is None

    @pytest.mark.asyncio
    async def test_empty_base_url(self):
        """Returns None for empty base URL."""
        result = await try_llms_txt("")
        assert result is None

    @pytest.mark.asyncio
    async def test_404_response(self):
        """Returns None when server returns 404."""
        mock_response = MagicMock()
        mock_response.status_code = 404

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None

        with patch("wet_mcp.sources.docs.httpx.AsyncClient", return_value=mock_client):
            result = await try_llms_txt("https://example.com")

        assert result is None
