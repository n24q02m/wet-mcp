"""Regression tests for the Cloudflare docs-store sync cutover."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch


def _enable_legacy_sync_settings(monkeypatch) -> None:
    from wet_mcp.config import settings

    monkeypatch.setenv("DOCS_DB_BACKEND", "cf-d1")
    monkeypatch.setattr(settings, "sync_enabled", True)
    monkeypatch.setattr(settings, "sync_s3_bucket", "legacy-bucket")
    monkeypatch.setattr(settings, "google_drive_client_id", "bundled-client")


def test_cf_d1_disables_every_sync_backend(monkeypatch) -> None:
    """D1 + Vectorize is authoritative even when legacy sync env is present."""
    _enable_legacy_sync_settings(monkeypatch)

    from wet_mcp.sync import resolve_active_backend

    assert resolve_active_backend() == "disabled"


async def test_gdrive_sync_full_is_disabled_on_cf_d1(monkeypatch) -> None:
    """A direct sync call must not write after the CF cutover."""
    _enable_legacy_sync_settings(monkeypatch)

    from wet_mcp.sync.gdrive import sync_full

    result = await sync_full(MagicMock())

    assert result["status"] == "disabled"


async def test_config_status_reports_effective_sync_state(monkeypatch) -> None:
    """Operator status must expose the effective writer, not the raw flag."""
    _enable_legacy_sync_settings(monkeypatch)

    import wet_mcp.server as server

    monkeypatch.setattr(server, "_docs_db", None)
    with (
        patch("wet_mcp.embedder.resolve_embed_backend_for_request", return_value=None),
        patch("wet_mcp.reranker.resolve_rerank_backend_for_request", return_value=None),
    ):
        status = await server._handle_config_status()

    assert status["sync"]["enabled"] is False
    assert status["sync"]["provider"] == "disabled"


def test_cloudflare_wrangler_templates_disable_legacy_sync() -> None:
    """The deployment contract must remain explicit if env defaults change."""
    root = Path(__file__).resolve().parents[1]
    for relative in ("wrangler.jsonc", "wrangler.deploy.template.jsonc"):
        content = (root / relative).read_text(encoding="utf-8")
        assert '"DOCS_DB_BACKEND": "cf-d1"' in content
        assert '"SYNC_ENABLED": "false"' in content
