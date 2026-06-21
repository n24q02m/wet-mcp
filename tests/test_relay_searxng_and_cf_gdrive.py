"""F10: SearXNG relay URL cred field. F9: skip GDrive device-code on Cloudflare.

F10 -- selecting SearXNG in the relay search chain used to surface no credential
field, so an external SearXNG instance could not be configured via the form.
F9 -- on Cloudflare the docs DB is D1 + Vectorize (durable), so the Google Drive
delta-sync is redundant; the relay must not trigger the GDrive device-code flow
there (it offered a non-functional setup).
"""

from __future__ import annotations

from unittest.mock import patch

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
