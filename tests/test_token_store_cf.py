"""Cloudflare-pilot token storage tests: encrypted tokens via PerPluginStore."""

import json

from mcp_core.storage.backends import InMemoryBackend

from wet_mcp.token_store import (
    load_token,
    load_token_for_sub,
    save_token,
    save_token_for_sub,
)


def test_save_token_encrypts_via_backend(monkeypatch):
    monkeypatch.setenv("CREDENTIAL_SECRET", "test-secret")
    mem = InMemoryBackend()
    token = {"access_token": "abc123", "refresh_token": "r", "token_type": "Bearer"}
    save_token("google_drive", token, backend=mem)

    blob = mem.get("wet/tokens/google_drive")
    assert blob is not None
    assert blob != json.dumps(token).encode()  # encrypted, not plaintext
    assert load_token("google_drive", backend=mem) == token


def test_load_missing_token_returns_none(monkeypatch):
    monkeypatch.setenv("CREDENTIAL_SECRET", "test-secret")
    assert load_token("google_drive", backend=InMemoryBackend()) is None


def test_token_file_on_disk_is_ciphertext(monkeypatch, tmp_path):
    """The new at-rest guarantee: the LocalFs token file is AES-GCM ciphertext.

    Replaces the obsolete plaintext-file + icacls/chmod model. An attacker who
    can read the file gets ciphertext, not the token. Non-vacuous: this fails
    if encryption were bypassed (plaintext written) -- we assert the access
    token string is absent from the raw bytes and the blob carries the
    PerPluginStore nonce(12) || ciphertext || tag(16) framing.
    """
    monkeypatch.setenv("CREDENTIAL_SECRET", "test-secret")
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    token = {"access_token": "super-secret-access-token", "token_type": "Bearer"}
    save_token("google_drive", token)  # no backend -> LocalFs default

    path = tmp_path / ".wet-mcp" / "tokens" / "google_drive.json"
    raw = path.read_bytes()
    # Non-vacuous: plaintext token must NOT appear anywhere in the file.
    assert b"super-secret-access-token" not in raw
    assert raw != json.dumps(token).encode()
    # nonce(12) + at least one ciphertext byte + tag(16)
    assert len(raw) >= 12 + 1 + 16
    # Round-trips back to the original token through the public contract.
    assert load_token("google_drive") == token


def test_token_file_posix_mode_is_0600(monkeypatch, tmp_path):
    """On POSIX, LocalFsBackend hardens the token file to 0o600.

    Skipped on Windows: mcp-core's LocalFsBackend only chmods on POSIX, and
    the file is encrypted at rest regardless of OS-level ACLs.
    """
    import os
    import stat

    if os.name == "nt":
        import pytest

        pytest.skip("LocalFsBackend chmod is POSIX-only; tokens are encrypted")

    monkeypatch.setenv("CREDENTIAL_SECRET", "test-secret")
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    save_token("google_drive", {"access_token": "abc"})

    path = tmp_path / ".wet-mcp" / "tokens" / "google_drive.json"
    mode = stat.S_IMODE(path.stat().st_mode)
    assert mode == 0o600


def test_multi_user_token_isolation(monkeypatch):
    monkeypatch.setenv("CREDENTIAL_SECRET", "test-secret")
    mem = InMemoryBackend()
    t1 = {"access_token": "u1-token"}
    t2 = {"access_token": "u2-token"}
    save_token_for_sub("user1", "google_drive", t1, backend=mem)
    save_token_for_sub("user2", "google_drive", t2, backend=mem)

    assert mem.get("wet/subs/user1/tokens/google_drive") is not None
    assert mem.get("wet/subs/user2/tokens/google_drive") is not None
    assert mem.get("wet/subs/user1/tokens/google_drive") != mem.get(
        "wet/subs/user2/tokens/google_drive"
    )
    assert load_token_for_sub("user1", "google_drive", backend=mem) == t1
    assert load_token_for_sub("user2", "google_drive", backend=mem) == t2
