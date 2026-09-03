"""F10: SearXNG relay URL cred field. F9: skip GDrive device-code on Cloudflare.

F10 -- selecting SearXNG in the relay search chain used to surface no credential
field, so an external SearXNG instance could not be configured via the form.
F9 -- on Cloudflare the docs DB is D1 + Vectorize (durable), so the Google Drive
delta-sync is redundant; the relay must not trigger the GDrive device-code flow
there (it offered a non-functional setup).
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from wet_mcp.relay_schema import RELAY_SCHEMA
from wet_mcp.relay_setup import ensure_config


def _field(key: str) -> dict | None:
    return next((f for f in RELAY_SCHEMA["fields"] if f.get("key") == key), None)


def test_searxng_surfaces_url_cred_field():
    """Selecting SearXNG must surface a derived SEARXNG_URL field."""
    search = _field("SEARCH_BACKENDS")
    assert search is not None
    assert search["providerKeys"].get("searxng") == "SEARXNG_URL"

    url_field = _field("SEARXNG_URL")
    assert url_field is not None
    assert url_field.get("derived") is True
    assert url_field.get("type") == "url"


def test_sync_redundant_on_cf(monkeypatch):
    from wet_mcp.credential_state import _sync_redundant_on_cf

    monkeypatch.delenv("DOCS_DB_BACKEND", raising=False)
    assert _sync_redundant_on_cf() is False
    monkeypatch.setenv("DOCS_DB_BACKEND", "cf-d1")
    assert _sync_redundant_on_cf() is True
    monkeypatch.setenv("DOCS_DB_BACKEND", "sqlite")
    assert _sync_redundant_on_cf() is False


def test_gdrive_device_code_skipped_on_cf(monkeypatch, tmp_path):
    """On CF (DOCS_DB_BACKEND=cf-d1) the GDrive device-code flow is not triggered."""
    monkeypatch.setenv("WET_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CREDENTIAL_SECRET", "s")
    monkeypatch.setenv("PUBLIC_URL", "https://wet.example.com")
    monkeypatch.setenv("DOCS_DB_BACKEND", "cf-d1")
    monkeypatch.delenv("MCP_STORAGE_BACKEND", raising=False)  # creds -> LocalFs (tmp)

    from wet_mcp import credential_state
    from wet_mcp.config import settings

    # Pretend GDrive client creds exist so only the CF gate would stop the flow.
    monkeypatch.setattr(settings, "google_drive_client_id", "cid", raising=False)
    monkeypatch.setattr(
        settings, "google_drive_client_secret", "csecret", raising=False
    )

    with patch("httpx.post") as mock_post:
        result = credential_state.save_credentials(
            {"JINA_AI_API_KEY": "k"}, {"sub": "user_a"}
        )

    assert mock_post.call_count == 0  # no device/code request on CF
    assert result is None  # no device-code next_step returned to the form


def test_gdrive_auto_sync_skipped_on_cf(monkeypatch):
    """F9 follow-up: the GDrive auto-sync LOOP must also not start on CF."""
    from wet_mcp.sync import gdrive as gdrive_mod

    monkeypatch.setattr(gdrive_mod.settings, "sync_enabled", True, raising=False)
    monkeypatch.setattr(gdrive_mod.settings, "sync_interval", 300, raising=False)
    monkeypatch.setattr(gdrive_mod, "_sync_task", None, raising=False)

    monkeypatch.setenv("DOCS_DB_BACKEND", "cf-d1")
    with (
        patch("asyncio.create_task") as mock_create,
        patch.object(gdrive_mod, "_auto_sync_loop"),
    ):
        gdrive_mod.start_auto_sync(MagicMock())
    assert mock_create.call_count == 0
    assert gdrive_mod._sync_task is None
    # Control: the same settings without the CF marker do start the loop task.
    monkeypatch.delenv("DOCS_DB_BACKEND", raising=False)
    with (
        patch("asyncio.create_task") as mock_create,
        patch.object(gdrive_mod, "_auto_sync_loop"),
    ):
        gdrive_mod.start_auto_sync(MagicMock())
    assert mock_create.call_count == 1


def _relay_session_stub() -> MagicMock:
    session = MagicMock()
    session.relay_url = "https://relay.example.com/authorize"
    session.session_id = "sess_test"
    return session


def _run_ensure_config(monkeypatch, tmp_path, cf: bool) -> AsyncMock:
    """Drive ensure_config(force=True) with the relay client fully faked."""
    monkeypatch.setenv("WET_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CREDENTIAL_SECRET", "s")
    monkeypatch.setenv("MCP_RELAY_URL", "https://relay.example.com")
    monkeypatch.delenv("MCP_STORAGE_BACKEND", raising=False)
    if cf:
        monkeypatch.setenv("DOCS_DB_BACKEND", "cf-d1")
    else:
        monkeypatch.delenv("DOCS_DB_BACKEND", raising=False)

    setup_mock = AsyncMock()
    with (
        patch(
            "mcp_core.relay.client.create_session",
            new=AsyncMock(return_value=_relay_session_stub()),
        ),
        patch(
            "mcp_core.relay.client.poll_for_result",
            new=AsyncMock(return_value={"JINA_AI_API_KEY": "k"}),
        ),
        patch("wet_mcp.relay_setup.PerPluginStore"),
        patch("wet_mcp.relay_setup.apply_config"),
        patch("httpx.AsyncClient") as mock_client,
        patch("wet_mcp.sync.setup_google_auth", setup_mock),
    ):
        http = MagicMock()
        http.__aenter__.return_value = MagicMock(post=AsyncMock())
        mock_client.return_value = http
        asyncio.run(ensure_config(force=True, timeout=1.0))
    return setup_mock


def test_relay_setup_gdrive_oauth_skipped_on_cf(monkeypatch, tmp_path):
    """F9: on CF the relay wizard must not run the GDrive OAuth setup either."""

    setup_mock = _run_ensure_config(monkeypatch, tmp_path, cf=True)
    assert setup_mock.await_count == 0


def test_relay_setup_gdrive_oauth_runs_off_cf(monkeypatch, tmp_path):
    """Control: without the CF marker the wizard still offers GDrive OAuth."""
    setup_mock = _run_ensure_config(monkeypatch, tmp_path, cf=False)
    assert setup_mock.await_count == 1
