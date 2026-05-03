"""Tests for HTTP multi-user credential wiring (per-sub contextvar).

Spec: ``~/projects/.superpower/mcp-core/specs/2026-05-01-stdio-pure-http-multiuser.md``
section 4.2 — per-tool-call handlers must resolve credentials by JWT
``sub`` set in the contextvar by the ``auth_scope`` middleware so
concurrent users do not see each other's API keys.

Memory: ``feedback_mcp_core_multi_user_state.md`` — mcp-core already
exposes per-/authorize sub UUIDs and SubjectContext callbacks; the gap
was on the consumer side (this plugin).
"""

from __future__ import annotations

import asyncio

import pytest

from wet_mcp.credential_state import (
    CLOUD_KEYS,
    credentials_for_current_request,
    get_current_sub,
    set_current_sub,
)


@pytest.fixture(autouse=True)
def _clear_contextvar_and_env(monkeypatch):
    """Each test starts with sub=None and no CLOUD_KEYS in env."""
    set_current_sub(None)
    for k in CLOUD_KEYS:
        monkeypatch.delenv(k, raising=False)
    yield
    set_current_sub(None)


class TestStdioModeUnchanged:
    """Stdio / single-user path: sub=None falls back to env vars."""

    def test_stdio_mode_returns_env_derived_creds(self, monkeypatch):
        monkeypatch.setenv("JINA_AI_API_KEY", "jina_env")
        monkeypatch.setenv("GEMINI_API_KEY", "gemini_env")

        assert get_current_sub() is None
        creds = credentials_for_current_request()

        assert creds == {
            "JINA_AI_API_KEY": "jina_env",
            "GEMINI_API_KEY": "gemini_env",
        }

    def test_stdio_mode_filters_non_cloud_env(self, monkeypatch):
        """Non-CLOUD_KEYS env vars must not leak into the result dict."""
        monkeypatch.setenv("JINA_AI_API_KEY", "jina_env")
        monkeypatch.setenv("PATH", "/usr/bin")
        monkeypatch.setenv("RANDOM_VAR", "noise")

        creds = credentials_for_current_request()

        assert creds == {"JINA_AI_API_KEY": "jina_env"}

    def test_stdio_mode_skips_empty_env(self, monkeypatch):
        """Empty-string env vars must be filtered (treated as unset)."""
        monkeypatch.setenv("JINA_AI_API_KEY", "")
        monkeypatch.setenv("GEMINI_API_KEY", "real_key")

        creds = credentials_for_current_request()

        assert creds == {"GEMINI_API_KEY": "real_key"}


class TestHttpSubIsolation:
    """HTTP multi-user path: each sub reads its own PerPluginStore bucket."""

    def test_http_sub_a_returns_a_creds(self, monkeypatch, tmp_path):
        """User A's contextvar -> A's creds via read_for_sub."""
        from unittest.mock import patch

        with patch(
            "wet_mcp.credential_state.read_for_sub",
            return_value={"JINA_AI_API_KEY": "jina_test_a"},
        ) as mock_read:
            set_current_sub("user-a")
            creds = credentials_for_current_request()

        mock_read.assert_called_once_with("user-a")
        assert creds == {"JINA_AI_API_KEY": "jina_test_a"}

    def test_http_sub_b_no_bleed_from_a(self, monkeypatch):
        """User B's contextvar -> B's creds, NOT A's."""
        from unittest.mock import patch

        store = {
            "user-a": {"JINA_AI_API_KEY": "jina_test_a"},
            "user-b": {"JINA_AI_API_KEY": "jina_test_b"},
        }

        def fake_read(sub: str) -> dict[str, str]:
            return store.get(sub, {})

        with patch(
            "wet_mcp.credential_state.read_for_sub",
            side_effect=fake_read,
        ):
            set_current_sub("user-b")
            creds = credentials_for_current_request()

        assert creds == {"JINA_AI_API_KEY": "jina_test_b"}
        assert creds.get("JINA_AI_API_KEY") != "jina_test_a"

    def test_http_no_sub_env_empty_returns_empty(self, monkeypatch):
        """sub=None + no CLOUD_KEYS in env -> empty dict (caller blocks)."""
        # Fixture already cleared everything.
        creds = credentials_for_current_request()
        assert creds == {}

    def test_http_sub_with_empty_store_returns_empty(self):
        """sub set but PerPluginStore returns {} -> empty dict."""
        from unittest.mock import patch

        with patch(
            "wet_mcp.credential_state.read_for_sub",
            return_value={},
        ):
            set_current_sub("brand-new-user")
            creds = credentials_for_current_request()

        assert creds == {}


class TestConcurrentSubsIsolation:
    """Concurrent asyncio tasks must see only their own sub.

    ``contextvars.ContextVar`` values are copied per task at creation
    via ``asyncio.create_task`` (Python 3.7+), so this exercises the
    PEP 567 guarantee that mcp-core's auth_scope wiring relies on.
    """

    async def test_concurrent_subs_isolation(self):
        from unittest.mock import patch

        store = {
            "user-a": {"JINA_AI_API_KEY": "jina_a"},
            "user-b": {"OPENAI_API_KEY": "oai_b"},
            "user-c": {"GEMINI_API_KEY": "gem_c"},
        }

        observed: dict[str, dict[str, str]] = {}
        # Synchronization barrier so all tasks set their sub before any
        # of them reads — proves isolation, not sequential ordering.
        barrier = asyncio.Event()

        def fake_read(sub: str) -> dict[str, str]:
            return store.get(sub, {})

        async def task_for(name: str) -> None:
            set_current_sub(name)
            await barrier.wait()
            observed[name] = credentials_for_current_request()

        with patch(
            "wet_mcp.credential_state.read_for_sub",
            side_effect=fake_read,
        ):
            tasks = [
                asyncio.create_task(task_for("user-a")),
                asyncio.create_task(task_for("user-b")),
                asyncio.create_task(task_for("user-c")),
            ]
            # Yield once so each task runs up to barrier.wait().
            await asyncio.sleep(0)
            barrier.set()
            await asyncio.gather(*tasks)

        assert observed["user-a"] == {"JINA_AI_API_KEY": "jina_a"}
        assert observed["user-b"] == {"OPENAI_API_KEY": "oai_b"}
        assert observed["user-c"] == {"GEMINI_API_KEY": "gem_c"}
        # Outer task's sub stayed None throughout (set inside child tasks
        # only, which propagate values back via PEP 567 task isolation).
        assert get_current_sub() is None


class TestPerRequestSubScopeCallback:
    """The auth_scope middleware sets/resets the contextvar around next_()."""

    async def test_sets_and_resets_around_next(self):
        from wet_mcp.server import _per_request_sub_scope

        observed: list[str | None] = []

        async def fake_next() -> None:
            observed.append(get_current_sub())

        assert get_current_sub() is None
        await _per_request_sub_scope({"sub": "user-x"}, fake_next)

        assert observed == ["user-x"]
        # Reset on the way out: outer scope must NOT leak the sub.
        assert get_current_sub() is None

    async def test_resets_even_on_exception(self):
        """If next_() raises, finally-block must still reset the contextvar."""
        from wet_mcp.server import _per_request_sub_scope

        async def boom() -> None:
            raise RuntimeError("downstream tool exploded")

        assert get_current_sub() is None
        with pytest.raises(RuntimeError, match="downstream tool exploded"):
            await _per_request_sub_scope({"sub": "user-x"}, boom)
        assert get_current_sub() is None

    async def test_handles_missing_sub_claim_as_none(self):
        """If JWT claims somehow lack ``sub``, treat as None (stdio fallback)."""
        from wet_mcp.server import _per_request_sub_scope

        observed: list[str | None] = []

        async def fake_next() -> None:
            observed.append(get_current_sub())

        await _per_request_sub_scope({}, fake_next)

        assert observed == [None]
        assert get_current_sub() is None
