"""E.1/E.2 setup-path gates: readiness-before-PUT + post-save poll."""

from __future__ import annotations

import wet_mcp.credential_state as cs


class _ReadyTrackingBackend:
    """InMemory-like backend that records ready()/put() call ordering."""

    def __init__(self) -> None:
        self.events: list[str] = []
        self.store: dict[str, bytes] = {}
        self._ready_returns = True

    def ready(self, retries: int = 8, delay: float = 0.5) -> bool:
        self.events.append("ready")
        return self._ready_returns

    def get(self, key):
        return self.store.get(key)

    def put(self, key, blob):
        self.events.append("put")
        self.store[key] = blob

    def delete(self, key):
        self.store.pop(key, None)


class _NoReadyBackend:
    """A backend WITHOUT a ready() method (like LocalFsBackend) -> _await must no-op."""

    def __init__(self) -> None:
        self.store: dict[str, bytes] = {}

    def get(self, key):
        return self.store.get(key)

    def put(self, key, blob):
        self.store[key] = blob

    def delete(self, key):
        self.store.pop(key, None)


def test_ready_is_awaited_before_first_put(monkeypatch):
    monkeypatch.setenv("CREDENTIAL_SECRET", "test-secret")
    monkeypatch.delenv("PUBLIC_URL", raising=False)  # single-user branch
    # Isolate the readiness gate from apply_config's provider re-init side effects.
    monkeypatch.setattr("wet_mcp.relay_setup.apply_config", lambda config: None)
    # isolate from the single-user GDrive device-code network call + spawn-cleanup timer
    monkeypatch.setattr("wet_mcp.config.settings.google_drive_client_id", "")
    monkeypatch.setattr(cs, "_schedule_spawn_cleanup", lambda *a, **k: None)
    backend = _ReadyTrackingBackend()
    monkeypatch.setattr(cs, "backend_from_env", lambda: backend)

    cs.save_credentials({"JINA_AI_API_KEY": "k"}, context={})

    # readiness probe ran BEFORE the credential PUT
    assert backend.events[0] == "ready"
    assert "put" in backend.events
    assert backend.events.index("ready") < backend.events.index("put")


def test_ready_not_called_for_backend_without_ready(monkeypatch):
    monkeypatch.setenv("CREDENTIAL_SECRET", "test-secret")
    monkeypatch.delenv("PUBLIC_URL", raising=False)
    monkeypatch.setattr("wet_mcp.relay_setup.apply_config", lambda config: None)
    # isolate from the single-user GDrive device-code network call + spawn-cleanup timer
    monkeypatch.setattr("wet_mcp.config.settings.google_drive_client_id", "")
    monkeypatch.setattr(cs, "_schedule_spawn_cleanup", lambda *a, **k: None)
    backend = _NoReadyBackend()  # no ready() attr -> _await_backend_ready must no-op
    monkeypatch.setattr(cs, "backend_from_env", lambda: backend)

    # must not raise (no ready()) and must still persist the credential blob
    cs.save_credentials({"JINA_AI_API_KEY": "k"}, context={})
    assert "wet/config" in backend.store


def test_poll_until_readable_returns_once_present(monkeypatch):
    monkeypatch.setenv("CREDENTIAL_SECRET", "test-secret")
    backend = _ReadyTrackingBackend()
    monkeypatch.setattr(cs, "backend_from_env", lambda: backend)
    # single-user key becomes readable after the save
    backend.store["wet/config"] = b"ciphertext"
    assert cs.poll_until_readable(None, retries=5, delay=0) is True


def test_poll_until_readable_times_out_gracefully(monkeypatch):
    monkeypatch.setenv("CREDENTIAL_SECRET", "test-secret")
    backend = _ReadyTrackingBackend()  # store stays empty -> never readable
    monkeypatch.setattr(cs, "backend_from_env", lambda: backend)
    assert cs.poll_until_readable("user-1", retries=3, delay=0) is False


def test_poll_until_readable_checks_sub_key(monkeypatch):
    monkeypatch.setenv("CREDENTIAL_SECRET", "test-secret")
    backend = _ReadyTrackingBackend()
    monkeypatch.setattr(cs, "backend_from_env", lambda: backend)
    backend.store["wet/subs/user-1/config"] = b"ciphertext"
    assert cs.poll_until_readable("user-1", retries=5, delay=0) is True
