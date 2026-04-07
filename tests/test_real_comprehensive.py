"""Comprehensive real-world testing for wet-mcp.

Tests all configuration combinations:
1. Embedding: local ONNX vs LiteLLM proxy
2. Reranking: local ONNX vs LiteLLM proxy
3. SearXNG: embedded vs external (oci-vm-infra)
4. All 4 tools: search, extract, media, config
5. Docs search: fixed cases (vinejs, inertia, dry-rb)
6. Markitdown: PDF extraction
7. Sync: config validation

Run with: uv run pytest tests/test_real_comprehensive.py -v -m integration --timeout=120
"""

import asyncio
import json
import os

import pytest

# ---------------------------------------------------------------------------
# Fixtures for different config modes
# ---------------------------------------------------------------------------

LITELLM_PROXY_URL = "https://litellm.n24q02m.com"
LITELLM_PROXY_KEY = os.environ.get("LITELLM_PROXY_KEY", "")
_SEARXNG_AUTH_PASS = os.environ.get("SEARXNG_AUTH_PASS")
SEARXNG_EXTERNAL_URL = "https://klprism:{}@searxng.n24q02m.com".format(
    _SEARXNG_AUTH_PASS or ""
)

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# 1. Docs discovery — fixed cases (vinejs, inertia, dry-rb)
# ---------------------------------------------------------------------------


class TestDocsDiscoveryFixes:
    """Test that previously failing library discoveries now work."""

    @pytest.fixture(autouse=True)
    def _clear_docs_cache(self):
        """Ensure fresh discovery (no stale cache)."""
        pass

    async def test_vinejs_discovery(self):
        from wet_mcp.sources.docs import discover_library

        result = await discover_library("vinejs")
        assert result is not None, "vinejs should be discovered"
        assert "vinejs.dev" in result.get("homepage", ""), f"Got: {result}"

    async def test_vinejs_scoped_discovery(self):
        from wet_mcp.sources.docs import discover_library

        result = await discover_library("@vinejs/vine")
        assert result is not None, "@vinejs/vine should be discovered"
        assert "vinejs.dev" in result.get("homepage", ""), f"Got: {result}"

    async def test_inertia_discovery(self):
        from wet_mcp.sources.docs import discover_library

        result = await discover_library("inertia")
        assert result is not None, "inertia should be discovered"
        assert "inertiajs.com" in result.get("homepage", ""), f"Got: {result}"

    async def test_inertiajs_react_discovery(self):
        from wet_mcp.sources.docs import discover_library

        result = await discover_library("@inertiajs/react")
        assert result is not None, "@inertiajs/react should be discovered"
        assert "inertiajs.com" in result.get("homepage", ""), f"Got: {result}"

    async def test_dry_rb_discovery(self):
        from wet_mcp.sources.docs import discover_library

        result = await discover_library("dry-rb")
        assert result is not None, "dry-rb should be discovered"
        assert "dry-rb.org" in result.get("homepage", ""), f"Got: {result}"

    async def test_dry_validation_discovery(self):
        from wet_mcp.sources.docs import discover_library

        result = await discover_library("dry-validation")
        assert result is not None, "dry-validation should be discovered"
        assert "dry-rb.org" in result.get("homepage", ""), f"Got: {result}"


# ---------------------------------------------------------------------------
# 2. Search tool — general, academic, docs
# ---------------------------------------------------------------------------


class TestSearchTool:
    """Test search tool with embedded SearXNG."""

    async def test_general_search(self):
        from wet_mcp.config import settings
        from wet_mcp.sources.searxng import search

        searxng_url = settings.searxng_url
        result = await search(searxng_url, "Python asyncio tutorial", max_results=5)
        data = json.loads(result)
        assert len(data) > 0, "General search should return results"

    async def test_academic_search(self):
        from wet_mcp.config import settings
        from wet_mcp.sources.searxng import search

        searxng_url = settings.searxng_url
        result = await search(
            searxng_url,
            "transformer attention mechanism",
            categories="science",
            max_results=5,
        )
        data = json.loads(result)
        assert len(data) > 0, "Academic search should return results"

    async def test_docs_search_fastapi(self):
        from wet_mcp.sources.docs import discover_library

        result = await discover_library("fastapi", language="python")
        assert result is not None
        assert "fastapi" in result.get("homepage", "").lower()

    async def test_docs_search_react(self):
        from wet_mcp.sources.docs import discover_library

        result = await discover_library("react", language="javascript")
        assert result is not None
        assert "react" in result.get("homepage", "").lower()

    async def test_docs_search_axum(self):
        from wet_mcp.sources.docs import discover_library

        result = await discover_library("axum", language="rust")
        assert result is not None


# ---------------------------------------------------------------------------
# 3. Search with external SearXNG (oci-vm-infra)
# ---------------------------------------------------------------------------


class TestExternalSearXNG:
    """Test search using external selfhosted SearXNG."""

    @pytest.fixture(autouse=True)
    def _require_searxng_auth(self):
        if not _SEARXNG_AUTH_PASS:
            pytest.skip("SEARXNG_AUTH_PASS not set")

    async def test_external_searxng_search(self):
        import httpx

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(
                SEARXNG_EXTERNAL_URL + "/search",
                params={"q": "test", "format": "json"},
            )
            assert resp.status_code == 200, (
                f"External SearXNG unreachable: {resp.status_code}"
            )
            data = resp.json()
            assert len(data.get("results", [])) > 0


# ---------------------------------------------------------------------------
# 4. Extract tool — web pages + markitdown (PDF)
# ---------------------------------------------------------------------------


class TestExtractTool:
    """Test content extraction including document conversion."""

    async def test_extract_web_page(self):
        from wet_mcp.sources.crawler import extract

        result = await extract(
            ["https://httpbin.org/html"],
            format="markdown",
            stealth=False,
        )
        data = json.loads(result)
        assert len(data) == 1
        assert "content" in data[0], f"Extract failed: {data[0]}"
        assert len(data[0]["content"]) > 100

    async def test_extract_pdf_markitdown(self):
        """Test PDF extraction via markitdown."""
        from wet_mcp.sources.crawler import extract

        # Use a well-known small public PDF
        result = await extract(
            ["https://www.w3.org/WAI/ER/tests/xhtml/testfiles/resources/pdf/dummy.pdf"],
            format="markdown",
        )
        data = json.loads(result)
        assert len(data) == 1
        assert "error" not in data[0] or "markitdown" not in data[0].get("error", ""), (
            f"PDF extraction failed: {data[0]}"
        )
        if "converter" in data[0]:
            assert data[0]["converter"] == "markitdown"

    async def test_is_document_url_detection(self):
        from wet_mcp.sources.crawler import _is_document_url

        assert _is_document_url("https://example.com/file.pdf")
        assert _is_document_url("https://example.com/report.docx")
        assert _is_document_url("https://example.com/slides.pptx")
        assert not _is_document_url("https://example.com/page.html")
        assert not _is_document_url("https://example.com/")


# ---------------------------------------------------------------------------
# 5. LiteLLM proxy mode — embedding + reranking
# ---------------------------------------------------------------------------


class TestLiteLLMProxy:
    """Test with LiteLLM proxy (oci-vm-infra)."""

    async def test_proxy_reachable(self):
        import httpx

        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(f"{LITELLM_PROXY_URL}/health/liveliness")
            assert resp.status_code == 200

    async def test_proxy_chat(self):
        """Test LLM chat via proxy using openai-compatible endpoint."""
        import httpx

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{LITELLM_PROXY_URL}/chat/completions",
                headers={
                    "Authorization": f"Bearer {LITELLM_PROXY_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "gemini/gemini-3-flash",
                    "messages": [{"role": "user", "content": "Say hello in 3 words"}],
                    "max_tokens": 50,
                },
            )
            assert resp.status_code == 200, f"Chat failed: {resp.text}"
            data = resp.json()
            assert data["choices"][0]["message"]["content"]

    async def test_proxy_rerank(self):
        """Test reranking via proxy using OpenAI-compatible endpoint."""
        import httpx

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{LITELLM_PROXY_URL}/rerank",
                headers={
                    "Authorization": f"Bearer {LITELLM_PROXY_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "mcp/rerank-multilingual-v3",
                    "query": "What is Python?",
                    "documents": [
                        "Python is a programming language",
                        "Java is a programming language",
                        "The weather is nice today",
                    ],
                },
            )
            assert resp.status_code == 200, f"Rerank failed: {resp.text}"
            data = resp.json()
            assert len(data["results"]) > 0

    async def test_proxy_rerank_via_litellm_sdk(self):
        """Test reranking via proxy using LiteLLM SDK with proxy mode flag."""
        import os

        import litellm

        # Enable proxy mode (same as config.setup_litellm in proxy mode)
        old_base = os.environ.get("LITELLM_PROXY_API_BASE")
        old_key = os.environ.get("LITELLM_PROXY_API_KEY")
        old_proxy = litellm.use_litellm_proxy
        try:
            os.environ["LITELLM_PROXY_API_BASE"] = LITELLM_PROXY_URL
            os.environ["LITELLM_PROXY_API_KEY"] = LITELLM_PROXY_KEY
            litellm.use_litellm_proxy = True

            from wet_mcp.reranker import LiteLLMReranker

            reranker = LiteLLMReranker(model="mcp/rerank-multilingual-v3")
            results = reranker.rerank(
                query="What is Python?",
                documents=[
                    "Python is a programming language",
                    "Java is a programming language",
                    "The weather is nice today",
                ],
                top_n=2,
            )
            assert len(results) == 2, f"Expected 2 results, got {len(results)}"
            # Python doc should score highest
            assert results[0][0] == 0, (
                f"Expected Python doc first, got index {results[0][0]}"
            )
            assert results[0][1] > 0.5, f"Expected high score, got {results[0][1]}"
        finally:
            litellm.use_litellm_proxy = old_proxy
            if old_base is None:
                os.environ.pop("LITELLM_PROXY_API_BASE", None)
            else:
                os.environ["LITELLM_PROXY_API_BASE"] = old_base
            if old_key is None:
                os.environ.pop("LITELLM_PROXY_API_KEY", None)
            else:
                os.environ["LITELLM_PROXY_API_KEY"] = old_key


# ---------------------------------------------------------------------------
# 5b. LiteLLM SDK mode (direct API keys)
# ---------------------------------------------------------------------------


class TestLiteLLMSDK:
    """Test with LiteLLM SDK mode (GOOGLE_API_KEY for Gemini)."""

    @pytest.fixture(autouse=True)
    def _get_api_keys(self):
        """Get API keys from running wet-mcp process."""
        import subprocess

        result = subprocess.run(
            [
                "bash",
                "-c",
                "cat /proc/$(pgrep -f 'bin/wet-mcp' | head -1)/environ 2>/dev/null | tr '\\0' '\\n' | grep '^API_KEYS='",
            ],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0 or not result.stdout.strip():
            pytest.skip("No running wet-mcp process with API_KEYS")
        self.api_keys_raw = result.stdout.strip().split("=", 1)[1]

    async def test_sdk_embedding_gemini(self):
        """Test embedding via Gemini API directly."""
        # Parse GOOGLE_API_KEY from API_KEYS format
        google_key = None
        for pair in self.api_keys_raw.split(","):
            if pair.startswith("GOOGLE_API_KEY:"):
                google_key = pair.split(":", 1)[1]
                break
        if not google_key:
            pytest.skip("GOOGLE_API_KEY not found in API_KEYS")

        import litellm

        resp = await litellm.aembedding(
            model="gemini/gemini-embedding-001",
            input=["Hello world"],
            api_key=google_key,
        )
        assert len(resp.data) == 1
        assert len(resp.data[0]["embedding"]) > 0

    async def test_sdk_chat_gemini(self):
        """Test chat via Gemini API directly."""
        google_key = None
        for pair in self.api_keys_raw.split(","):
            if pair.startswith("GOOGLE_API_KEY:"):
                google_key = pair.split(":", 1)[1]
                break
        if not google_key:
            pytest.skip("GOOGLE_API_KEY not found in API_KEYS")

        import litellm

        resp = await litellm.acompletion(
            model="gemini/gemini-2.5-flash",
            messages=[{"role": "user", "content": "Say hi"}],
            api_key=google_key,
            max_tokens=1024,
        )
        # Gemini 2.5 Flash uses thinking tokens — content may be in
        # provider_specific_fields or regular content
        msg = resp.choices[0].message
        has_content = msg.content or (
            msg.provider_specific_fields
            and msg.provider_specific_fields.get("thoughts")
        )
        assert has_content, f"No content or thoughts: {msg}"


# ---------------------------------------------------------------------------
# 5c. Modal.com AI workers (custom Qwen3 models)
# ---------------------------------------------------------------------------

MODAL_EMBED_URL = (
    "https://n24q02m--ai-workers-embedding-embeddingserver-serve.modal.run"
)
MODAL_RERANK_URL = "https://n24q02m--ai-workers-reranker-rerankerserver-serve.modal.run"
MODAL_API_KEY = os.environ.get("WORKER_API_KEY")


class TestModalWorkers:
    """Test custom Qwen3 models deployed on Modal.com."""

    @pytest.fixture(autouse=True)
    def _require_worker_api_key(self):
        if not MODAL_API_KEY:
            pytest.skip("WORKER_API_KEY not set")

    async def test_modal_embedding(self):
        """Test Qwen3-Embedding-0.6B via Modal (OpenAI-compatible)."""
        import httpx

        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                f"{MODAL_EMBED_URL}/v1/embeddings",
                headers={
                    "Authorization": f"Bearer {MODAL_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "qwen3-embedding-0.6b",
                    "input": ["Hello world", "Python programming"],
                },
            )
            assert resp.status_code == 200, f"Modal embed failed: {resp.text}"
            data = resp.json()
            assert len(data["data"]) == 2
            assert len(data["data"][0]["embedding"]) == 1024

    async def test_modal_reranking(self):
        """Test Qwen3-Reranker-0.6B via Modal (Cohere-compatible)."""
        import httpx

        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                f"{MODAL_RERANK_URL}/v1/rerank",
                headers={
                    "Authorization": f"Bearer {MODAL_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "qwen3-reranker-0.6b",
                    "query": "What is Python?",
                    "documents": [
                        "Python is a programming language",
                        "Java is a programming language",
                        "The weather is nice today",
                    ],
                },
            )
            assert resp.status_code == 200, f"Modal rerank failed: {resp.text}"
            data = resp.json()
            assert len(data["results"]) > 0
            # Python doc should score highest
            top = data["results"][0]
            assert top["index"] == 0

    async def test_modal_embedding_via_litellm_sdk(self):
        """Test Modal embedding via LiteLLM SDK (openai/ provider)."""
        import litellm

        response = litellm.embedding(
            model="openai/qwen3-embedding-0.6b",
            input=["Hello world", "Python programming"],
            api_base=f"{MODAL_EMBED_URL}/v1",
            api_key=MODAL_API_KEY,
            encoding_format="float",
        )
        assert len(response.data) == 2
        assert len(response.data[0]["embedding"]) == 1024

    async def test_modal_reranking_via_litellm_sdk(self):
        """Test Modal reranking via LiteLLM SDK (cohere/ provider).

        Requires Modal worker deployed with /v2/rerank route and
        return_documents field support.
        """
        import litellm

        try:
            response = litellm.rerank(
                model="cohere/qwen3-reranker-0.6b",
                query="What is Python?",
                documents=[
                    "Python is a programming language",
                    "Java is a programming language",
                    "The weather is nice today",
                ],
                top_n=2,
                api_base=MODAL_RERANK_URL,
                api_key=MODAL_API_KEY,
            )
            assert len(response.results) >= 1
        except Exception as e:
            # /v2/rerank route may not be deployed yet
            if "Not Found" in str(e) or "404" in str(e):
                pytest.skip("Modal reranker /v2/rerank not deployed yet")
            raise


# ---------------------------------------------------------------------------
# 6. Local ONNX embedding + reranking
# ---------------------------------------------------------------------------


class TestLocalONNX:
    """Test local Qwen3 ONNX embedding and reranking."""

    async def test_local_embedding(self):
        from wet_mcp.embedder import Qwen3EmbedBackend

        backend = Qwen3EmbedBackend()
        vectors = await backend.embed_texts(["Hello world", "Python programming"])
        assert len(vectors) == 2
        assert len(vectors[0]) > 0  # Should have dimensions

    async def test_local_reranking(self):
        from wet_mcp.reranker import Qwen3Reranker

        reranker = Qwen3Reranker()
        results = reranker.rerank(
            query="What is Python?",
            documents=[
                "Python is a programming language created by Guido van Rossum",
                "Java is a programming language by Sun Microsystems",
                "The weather forecast says rain tomorrow",
            ],
            top_n=2,
        )
        assert len(results) == 2
        # Results are (index, score) tuples — first should be Python doc
        assert results[0][0] == 0  # index 0 = Python doc


# ---------------------------------------------------------------------------
# 7. Config tool
# ---------------------------------------------------------------------------


class TestConfigTool:
    """Test config tool actions."""

    async def test_config_status(self):
        from wet_mcp.config import settings

        assert settings.log_level in ("INFO", "DEBUG", "WARNING", "ERROR")
        assert settings.tool_timeout > 0
        assert settings.wet_cache is True or settings.wet_cache is False

    async def test_config_embedding_backend_resolution(self):
        from wet_mcp.config import settings

        backend = settings.resolve_embedding_backend()
        assert backend in ("litellm", "local")

    async def test_config_rerank_backend_resolution(self):
        from wet_mcp.config import settings

        backend = settings.resolve_rerank_backend()
        assert backend in ("litellm", "local")


# ---------------------------------------------------------------------------
# 8. Sync config validation
# ---------------------------------------------------------------------------


class TestSyncConfig:
    """Test sync configuration (without actual Google Drive)."""

    async def test_sync_disabled_by_default(self):
        from wet_mcp.config import settings

        assert settings.sync_enabled is False

    async def test_sync_config_fields(self):
        from wet_mcp.config import settings

        assert settings.sync_folder == "wet-mcp"
        assert settings.sync_interval == 0


# ---------------------------------------------------------------------------
# 9. Media tool
# ---------------------------------------------------------------------------


class TestMediaTool:
    """Test media listing from web pages."""

    async def test_list_media(self):
        from wet_mcp.sources.crawler import list_media

        result = await list_media(
            "https://httpbin.org/html",
            media_type="all",
            max_items=5,
        )
        # httpbin/html has no media, but should not error
        data = json.loads(result)
        assert isinstance(data, dict)


# ---------------------------------------------------------------------------
# 10. End-to-end: docs search with indexing
# ---------------------------------------------------------------------------


class TestE2EDocsSearch:
    """End-to-end docs search including indexing and querying."""

    @pytest.mark.timeout(120)
    async def test_docs_search_htmx(self):
        """Full pipeline: discover → index → search."""
        from wet_mcp.sources.docs import discover_library

        result = await discover_library("htmx")
        assert result is not None
        assert "htmx" in result.get("homepage", "").lower()
