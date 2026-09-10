"""F10: SearXNG relay URL cred field. F9: skip GDrive device-code on Cloudflare.

F10 -- selecting SearXNG in the relay search chain used to surface no credential
field, so an external SearXNG instance could not be configured via the form.
F9 -- on Cloudflare the docs DB is D1 + Vectorize (durable), so the Google Drive
delta-sync is redundant; the relay must not trigger the GDrive device-code flow
there (it offered a non-functional setup).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from wet_mcp.relay_schema import RELAY_SCHEMA


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


@pytest.fixture
def local_gdrive_settings(monkeypatch):
    from wet_mcp.config import settings

    monkeypatch.delenv("DOCS_DB_BACKEND", raising=False)
    monkeypatch.setattr(settings, "docs_db_backend", "sqlite")
    monkeypatch.setattr(settings, "sync_enabled", True)
    monkeypatch.setattr(settings, "sync_s3_bucket", "")
    monkeypatch.setattr(settings, "sync_interval", 300)
    monkeypatch.setattr(settings, "google_drive_client_id", "fixture-client")
    monkeypatch.setattr(settings, "google_drive_client_secret", "fixture-secret")
    return settings


@pytest.fixture(params=["cf-env", "cf-settings", "sync-disabled", "s3"])
def inactive_gdrive(request, monkeypatch, local_gdrive_settings):
    settings = local_gdrive_settings
    if request.param == "cf-env":
        monkeypatch.setenv("DOCS_DB_BACKEND", "cf-d1")
        monkeypatch.setattr(settings, "sync_s3_bucket", "legacy-bucket")
    elif request.param == "cf-settings":
        monkeypatch.setattr(settings, "docs_db_backend", "cf-d1")
    elif request.param == "sync-disabled":
        monkeypatch.setattr(settings, "sync_enabled", False)
    else:
        monkeypatch.setattr(settings, "sync_s3_bucket", "active-bucket")


async def _run_relay_wizard(monkeypatch, setup_auth):
    from wet_mcp.relay_setup import ensure_config

    config = {"COHERE_API_KEY": "fixture-key"}
    monkeypatch.setenv("MCP_RELAY_URL", "https://relay.example.com")
    monkeypatch.setattr(
        "mcp_core.relay.client.create_session",
        AsyncMock(
            return_value=MagicMock(
                relay_url="https://relay.example.com/authorize",
                session_id="fixture-session",
            )
        ),
    )
    monkeypatch.setattr(
        "mcp_core.relay.client.poll_for_result", AsyncMock(return_value=config)
    )
    monkeypatch.setattr("wet_mcp.relay_setup.PerPluginStore", MagicMock())
    monkeypatch.setattr("wet_mcp.relay_setup.apply_config", lambda _config: None)
    monkeypatch.setattr("httpx.AsyncClient.post", AsyncMock())
    monkeypatch.setattr("wet_mcp.sync.setup_google_auth", setup_auth)
    assert await ensure_config(force=True, timeout=1) == config


async def test_inactive_gdrive_never_starts_oauth_or_sync(inactive_gdrive, monkeypatch):
    from wet_mcp.credential_state import _trigger_gdrive_device_code
    from wet_mcp.sync import gdrive

    sync_post = MagicMock(return_value=MagicMock(status_code=400))
    async_post = AsyncMock(return_value=MagicMock(status_code=400))
    scheduled = []

    def record_task(coro):
        scheduled.append(True)
        coro.close()
        return MagicMock()

    monkeypatch.setattr("httpx.post", sync_post)
    monkeypatch.setattr("httpx.AsyncClient.post", async_post)
    monkeypatch.setattr("asyncio.create_task", record_task)
    monkeypatch.setattr(gdrive, "_sync_task", None)

    assert _trigger_gdrive_device_code(sub="fixture-sub") is None
    assert await gdrive.setup_google_auth() is False
    gdrive.start_auto_sync(MagicMock())
    assert sync_post.call_count == 0
    assert async_post.await_count == 0
    assert scheduled == []

    setup_auth = AsyncMock(return_value=True)
    await _run_relay_wizard(monkeypatch, setup_auth)
    setup_auth.assert_not_awaited()


async def test_local_gdrive_keeps_oauth_and_auto_sync(
    local_gdrive_settings, monkeypatch
):
    from wet_mcp.credential_state import _trigger_gdrive_device_code
    from wet_mcp.sync import gdrive

    sync_post = MagicMock(return_value=MagicMock(status_code=400))
    async_post = AsyncMock(return_value=MagicMock(status_code=400))
    scheduled = []

    def record_task(coro):
        scheduled.append(True)
        coro.close()
        return MagicMock()

    monkeypatch.setattr("httpx.post", sync_post)
    monkeypatch.setattr("httpx.AsyncClient.post", async_post)
    monkeypatch.setattr("asyncio.create_task", record_task)
    monkeypatch.setattr(gdrive, "_sync_task", None)

    _trigger_gdrive_device_code(sub="fixture-sub")
    await gdrive.setup_google_auth()
    gdrive.start_auto_sync(MagicMock())
    assert sync_post.call_args.args[0] == "https://oauth2.googleapis.com/device/code"
    assert async_post.call_args.args[0] == "https://oauth2.googleapis.com/device/code"
    assert scheduled == [True]

    setup_auth = AsyncMock(return_value=True)
    await _run_relay_wizard(monkeypatch, setup_auth)
    setup_auth.assert_awaited_once()
