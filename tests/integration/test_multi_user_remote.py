"""Per-sub credential isolation in wet-mcp remote multi-user mode."""

from __future__ import annotations

import pytest


@pytest.mark.integration
def test_two_subs_isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("WET_DATA_DIR", str(tmp_path))
    from wet_mcp.credential_state import read_for_sub, store_for_sub

    store_for_sub("user_a", {"JINA_AI_API_KEY": "key_a"})
    store_for_sub("user_b", {"JINA_AI_API_KEY": "key_b"})

    assert read_for_sub("user_a") == {"JINA_AI_API_KEY": "key_a"}
    assert read_for_sub("user_b") == {"JINA_AI_API_KEY": "key_b"}
    assert read_for_sub("user_a") != read_for_sub("user_b")


@pytest.mark.integration
def test_save_credentials_uses_sub_when_public_url_set(tmp_path, monkeypatch):
    monkeypatch.setenv("WET_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("PUBLIC_URL", "https://wet.example.com")
    # Disable GDrive trigger so this test stays focused on per-sub config
    # storage. The GDrive multi-user trigger has its own coverage in the
    # unit suite.
    from wet_mcp.config import settings as s

    monkeypatch.setattr(s, "google_drive_client_id", "", raising=False)
    monkeypatch.setattr(s, "google_drive_client_secret", "", raising=False)

    from wet_mcp.credential_state import read_for_sub, save_credentials

    save_credentials({"JINA_AI_API_KEY": "k1"}, {"sub": "user_a"})
    save_credentials({"JINA_AI_API_KEY": "k2"}, {"sub": "user_b"})

    assert read_for_sub("user_a")["JINA_AI_API_KEY"] == "k1"
    assert read_for_sub("user_b")["JINA_AI_API_KEY"] == "k2"


@pytest.mark.integration
def test_save_credentials_multi_user_triggers_gdrive_per_sub(tmp_path, monkeypatch):
    """Multi-user branch starts the device-code flow when a Google client
    is configured, returning ``oauth_device_code`` for the relay form and
    persisting tokens under the per-sub directory rather than the shared
    one."""
    monkeypatch.setenv("WET_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("PUBLIC_URL", "https://wet.example.com")
    from wet_mcp.config import settings as s

    monkeypatch.setattr(s, "google_drive_client_id", "test-client-id", raising=False)
    monkeypatch.setattr(
        s, "google_drive_client_secret", "test-client-secret", raising=False
    )

    fake_device_response = {
        "device_code": "dc-abc",
        "user_code": "ABC-123",
        "verification_url": "https://www.google.com/device",
        "interval": 5,
        "expires_in": 600,
    }

    class _FakeResponse:
        status_code = 200

        def json(self):
            return fake_device_response

    def _fake_post(url, data, timeout):  # noqa: ARG001
        return _FakeResponse()

    monkeypatch.setattr("httpx.post", _fake_post)

    from wet_mcp.credential_state import save_credentials

    result = save_credentials({"JINA_AI_API_KEY": "k1"}, {"sub": "user_a"})

    assert result == {
        "type": "oauth_device_code",
        "verification_url": "https://www.google.com/device",
        "user_code": "ABC-123",
    }
