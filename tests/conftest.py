"""Pytest configuration and fixtures."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytest_plugins = ["conftest_e2e", "conftest_cf"]


@pytest.fixture(autouse=True)
def _stub_phase2_lifespan_hooks():
    """Phase 2 wires migrations + Tier 1 warmup into the FastMCP lifespan.

    Both touch ``~/.wet-mcp/docs.db`` which the CI runner does not have.
    Stub them out by default so tests that drive the lifespan don't hit
    real disk; tests that need the real migrations / warmup call them
    directly (test_migrations.py, test_tier1_warmup.py).

    Also stubs the embedding/reranker backend FACTORIES so the lifespan's
    fire-and-forget background init task (``wet-init-backends``) never loads a
    real local ONNX model (~570MB download) nor makes a real cloud provider
    call -- either of which hangs a cold CI runner long after a test's own
    patches have exited. Tests that exercise these init factories patch the
    same targets themselves; their patch overrides this default.
    """
    embed_backend = MagicMock()
    embed_backend.check_available = AsyncMock(return_value=768)
    rerank = MagicMock()
    rerank.check_available = MagicMock(return_value=True)
    with (
        patch("wet_mcp.migrations.run_migrations_on_startup"),
        patch("wet_mcp.sources.tier1_warmup.maybe_warm"),
        patch("wet_mcp.embedder.init_backend", return_value=embed_backend),
        patch("wet_mcp.reranker.init_reranker", return_value=rerank),
    ):
        yield


@pytest.fixture(autouse=True)
def _disable_uvx_tool_venv_detection(monkeypatch):
    """Default ``is_uvx_tool_venv`` to ``False`` for all tests.

    The real detection inspects the dev ``.venv`` (which also lacks pip in
    uv-managed projects) and would otherwise short-circuit search-tool
    tests. Tests that exercise the uvx detection itself reset
    ``transport_check._UVX_TOOL_VENV_CACHE`` and patch the underlying
    signals directly.
    """
    import sys

    import wet_mcp.transport_check as tc

    monkeypatch.setattr(tc, "is_uvx_tool_venv", lambda: False)
    # ``test_server_timeout.py`` re-imports ``wet_mcp.server`` under heavy
    # mocking; patch every live copy registered in ``sys.modules`` so
    # subsequent tests still see ``False``.
    for mod_name, mod in list(sys.modules.items()):
        if mod_name == "wet_mcp.server" and hasattr(mod, "is_uvx_tool_venv"):
            monkeypatch.setattr(mod, "is_uvx_tool_venv", lambda: False)
    yield


@pytest.fixture(autouse=True)
def _set_credential_state_configured():
    """Set credential state to CONFIGURED for all tests.

    Prevents _require_credentials() from blocking tool calls in tests.
    Tests that specifically test credential state should override this.
    """
    from wet_mcp.credential_state import CredentialState, set_state

    set_state(CredentialState.CONFIGURED)
    yield
    set_state(CredentialState.CONFIGURED)


@pytest.fixture
def sample_url():
    """Sample URL for testing."""
    return "https://example.com"


@pytest.fixture
def sample_query():
    """Sample search query."""
    return "test query"


@pytest.fixture(autouse=True)
async def _reset_crawler_singleton():
    """Reset the crawler singleton state before and after each test.

    This ensures tests do not leak state between each other when the
    singleton browser pool is involved.
    """
    import wet_mcp.sources.crawler as crawler_mod

    # Reset before test
    crawler_mod._crawler_instance = None
    crawler_mod._crawler_stealth = False
    crawler_mod._browser_semaphore = None

    yield

    # Reset after test
    crawler_mod._crawler_instance = None
    crawler_mod._crawler_stealth = False
    crawler_mod._browser_semaphore = None


@pytest.fixture
def mock_crawler_instance():
    """Create a mock AsyncWebCrawler instance for use with _get_crawler patch.

    Returns the mock instance directly.  Tests should patch
    ``wet_mcp.sources.crawler._get_crawler`` to return this mock so that
    the singleton browser pool is bypassed entirely.

    Example usage::

        async def test_something(mock_crawler_instance):
            mock_result = MagicMock(success=True, ...)
            mock_crawler_instance.arun = AsyncMock(return_value=mock_result)

            with patch(
                "wet_mcp.sources.crawler._get_crawler",
                new_callable=AsyncMock,
                return_value=mock_crawler_instance,
            ):
                result = await extract(["https://example.com"])
    """
    instance = AsyncMock()
    instance.__aenter__ = AsyncMock(return_value=instance)
    instance.__aexit__ = AsyncMock(return_value=None)
    return instance
