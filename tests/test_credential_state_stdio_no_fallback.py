"""Regression test: stdio mode must NOT fallback to PerPluginStore.

Per spec 2026-05-01-stdio-pure-http-multiuser.md §4.1 + OQ3:
"Stdio mode reads credentials from env vars ONLY". PerPluginStore is
HTTP-mode persistence for resilience across server restarts -- stdio
mode must skip it entirely.
"""

from __future__ import annotations

import os
import sys
from unittest.mock import patch

import pytest

from wet_mcp.credential_state import (
    CLOUD_KEYS,
    CredentialState,
    resolve_credential_state,
)


@pytest.fixture(autouse=True)
def _reset_module_state():
    """Reset module-level state before each test."""
    import wet_mcp.credential_state as mod

    mod._state = CredentialState.AWAITING_SETUP
    mod._setup_url = None
    yield
    mod._state = CredentialState.AWAITING_SETUP
    mod._setup_url = None


def test_stdio_skips_per_plugin_store(monkeypatch):
    """Stdio mode + env empty + saved config has cloud keys -> NOT CONFIGURED.

    The bug: ``resolve_credential_state`` previously read PerPluginStore in
    stdio mode, mutating ``os.environ`` from a persisted file. Per spec
    2026-05-01 §4.1 + OQ3, stdio reads env vars ONLY -- if env empty, the
    server falls through to AWAITING_SETUP / LOCAL without touching the
    per-plugin store.
    """
    # Empty env (no CLOUD_KEYS, no HTTP markers).
    for k in CLOUD_KEYS:
        monkeypatch.delenv(k, raising=False)
    monkeypatch.delenv("MCP_TRANSPORT", raising=False)
    monkeypatch.delenv("TRANSPORT_MODE", raising=False)
    monkeypatch.setattr(sys, "argv", ["wet-mcp"])

    # PerPluginStore.load() must NOT be called in stdio mode. Patch it to
    # return a populated config and assert it stays untouched.
    with (
        patch("wet_mcp.credential_state.PerPluginStore") as mock_store_class,
        patch(
            "mcp_core.get_mode",
            return_value=None,
        ),
    ):
        mock_store_class.return_value.load.return_value = {
            "GEMINI_API_KEY": "should-not-load"
        }
        state = resolve_credential_state()

        # Assertion: stdio mode skipped the PerPluginStore branch entirely
        # (it must not have been instantiated for the fallback read).
        mock_store_class.assert_not_called()

    # Env must NOT have been mutated by the (skipped) store load.
    assert os.environ.get("GEMINI_API_KEY") is None

    # State falls through to AWAITING_SETUP because get_mode is None and
    # there are no env CLOUD_KEYS. CONFIGURED would indicate the bug.
    assert state == CredentialState.AWAITING_SETUP


def test_stdio_with_env_var_still_configured(monkeypatch):
    """Stdio mode + env CLOUD_KEY present -> CONFIGURED (env path unaffected by fix)."""
    for k in CLOUD_KEYS:
        monkeypatch.delenv(k, raising=False)
    monkeypatch.delenv("MCP_TRANSPORT", raising=False)
    monkeypatch.delenv("TRANSPORT_MODE", raising=False)
    monkeypatch.setattr(sys, "argv", ["wet-mcp"])
    monkeypatch.setenv("GEMINI_API_KEY", "env-provided-key")

    state = resolve_credential_state()
    assert state == CredentialState.CONFIGURED
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)


def test_http_mode_uses_per_plugin_store_via_mcp_transport(monkeypatch):
    """HTTP mode (MCP_TRANSPORT=http): fallback IS allowed for self-host persistence."""
    for k in CLOUD_KEYS:
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("MCP_TRANSPORT", "http")

    with patch(
        "mcp_core.storage.per_plugin_store.PerPluginStore.load",
        return_value={"GEMINI_API_KEY": "http-load-ok"},
    ):
        state = resolve_credential_state()

    assert state == CredentialState.CONFIGURED
    assert os.environ.get("GEMINI_API_KEY") == "http-load-ok"
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)


def test_http_mode_uses_per_plugin_store_via_transport_mode(monkeypatch):
    """HTTP mode (TRANSPORT_MODE=http): fallback IS allowed."""
    for k in CLOUD_KEYS:
        monkeypatch.delenv(k, raising=False)
    monkeypatch.delenv("MCP_TRANSPORT", raising=False)
    monkeypatch.setenv("TRANSPORT_MODE", "http")

    with patch(
        "mcp_core.storage.per_plugin_store.PerPluginStore.load",
        return_value={"JINA_AI_API_KEY": "http-jina"},
    ):
        state = resolve_credential_state()

    assert state == CredentialState.CONFIGURED
    assert os.environ.get("JINA_AI_API_KEY") == "http-jina"
    monkeypatch.delenv("JINA_AI_API_KEY", raising=False)


def test_http_mode_uses_per_plugin_store_via_argv_flag(monkeypatch):
    """HTTP mode (--http argv flag): fallback IS allowed."""
    for k in CLOUD_KEYS:
        monkeypatch.delenv(k, raising=False)
    monkeypatch.delenv("MCP_TRANSPORT", raising=False)
    monkeypatch.delenv("TRANSPORT_MODE", raising=False)
    monkeypatch.setattr(sys, "argv", ["wet-mcp", "--http"])

    with patch(
        "mcp_core.storage.per_plugin_store.PerPluginStore.load",
        return_value={"OPENAI_API_KEY": "http-openai"},
    ):
        state = resolve_credential_state()

    assert state == CredentialState.CONFIGURED
    assert os.environ.get("OPENAI_API_KEY") == "http-openai"
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)


def test_stdio_local_mode_marker_still_works(monkeypatch):
    """Stdio mode + local marker -> LOCAL state (path 3 unaffected by fix)."""
    for k in CLOUD_KEYS:
        monkeypatch.delenv(k, raising=False)
    monkeypatch.delenv("MCP_TRANSPORT", raising=False)
    monkeypatch.delenv("TRANSPORT_MODE", raising=False)
    monkeypatch.setattr(sys, "argv", ["wet-mcp"])

    with (
        patch("wet_mcp.credential_state.PerPluginStore") as mock_store_class,
        patch(
            "mcp_core.get_mode",
            return_value="local",
        ),
    ):
        # Even if PerPluginStore would have data, stdio must not touch it.
        mock_store_class.return_value.load.return_value = {"GEMINI_API_KEY": "x"}
        state = resolve_credential_state()
        mock_store_class.assert_not_called()

    assert state == CredentialState.LOCAL
