"""Tests for wet_mcp.token_store module."""

from unittest.mock import patch

import pytest

from wet_mcp.token_store import (
    _get_token_dir,
    _get_token_dir_for_sub,
    delete_token,
    get_token_path,
    get_token_path_for_sub,
    load_token,
    load_token_for_sub,
    read_token_for_sub,
    save_token,
    save_token_for_sub,
)


@pytest.fixture
def token_dir(tmp_path, monkeypatch):
    """Provide a temp token directory and patch settings.

    ``get_token_path`` / ``_get_token_dir`` (path-shape helpers) read
    ``settings.get_data_dir()``, so keep patching settings for the helper
    tests. The encrypted store routes through ``PerPluginStore`` +
    ``LocalFsBackend``, which key off ``Path.home()`` -- redirect that to a
    temp dir too so ``save_token`` / ``load_token`` round-trips stay isolated
    and never touch the real ``~/.wet-mcp``.
    """
    d = tmp_path / "tokens"
    d.mkdir()
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    monkeypatch.setenv("CREDENTIAL_SECRET", "test-secret")
    with patch("wet_mcp.token_store.settings") as mock_settings:
        mock_settings.get_data_dir.return_value = tmp_path
        yield d


def test_get_token_dir(token_dir):
    """Test _get_token_dir helper."""
    assert _get_token_dir() == token_dir


def test_get_token_path(token_dir):
    """Test get_token_path returns correct provider path."""
    assert get_token_path("drive") == token_dir / "drive.json"


def test_path_traversal_validation(token_dir):
    """Test that path traversal sequences are blocked."""
    with pytest.raises(ValueError, match="Invalid path component"):
        get_token_path("../drive")

    with pytest.raises(ValueError, match="Invalid path component"):
        get_token_path("drive/something")

    with pytest.raises(ValueError, match="Invalid path component"):
        get_token_path_for_sub("../user", "drive")

    with pytest.raises(ValueError, match="Invalid path component"):
        get_token_path_for_sub("user", "../drive")

    with pytest.raises(ValueError, match="Name cannot be empty"):
        get_token_path("")


def test_load_missing_token(token_dir):
    """load_token returns None if file doesn't exist."""
    assert load_token("drive") is None


def test_save_and_load_token(token_dir, tmp_path):
    """Test standard save and load flow (encrypted blob via LocalFsBackend)."""
    token = {"access_token": "abc123", "token_type": "Bearer"}
    save_token("drive", token)

    loaded = load_token("drive")
    assert loaded == token

    # Verify the encrypted token file landed under the LocalFs layout.
    assert (tmp_path / ".wet-mcp" / "tokens" / "drive.json").exists()


def test_delete_token(token_dir, tmp_path):
    """delete_token clears a stored token so load_token returns None afterward."""
    token = {"access_token": "abc123", "token_type": "Bearer"}
    save_token("drive", token)
    assert load_token("drive") == token

    delete_token("drive")

    assert load_token("drive") is None


def test_delete_token_missing_is_noop(token_dir):
    """delete_token on a provider with no stored token does not raise."""
    delete_token("drive")
    assert load_token("drive") is None


def test_load_corrupt_blob_returns_none(token_dir, tmp_path):
    """load_token returns None when the on-disk blob is not decryptable.

    Tokens are AES-GCM ciphertext now, so arbitrary garbage bytes fail to
    decrypt -> treated as absent (re-auth lifecycle preserved).
    """
    path = tmp_path / ".wet-mcp" / "tokens" / "drive.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"not a valid aes-gcm blob")
    assert load_token("drive") is None


def test_load_non_dict_payload(token_dir):
    """load_token returns None if the decrypted payload is not a dictionary."""
    from mcp_core.storage.backends import InMemoryBackend
    from mcp_core.storage.per_plugin_store import PerPluginStore

    mem = InMemoryBackend()
    # Encrypt a non-dict payload through the store, then read via load_token.
    store = PerPluginStore("wet", None, backend=mem, sub_key="tokens/drive")
    non_dict_payload: object = [1, 2, 3]
    store.save(non_dict_payload)  # type: ignore
    assert load_token("drive", backend=mem) is None


def test_load_no_access_token(token_dir):
    """load_token returns None if access_token key is missing."""
    from mcp_core.storage.backends import InMemoryBackend
    from mcp_core.storage.per_plugin_store import PerPluginStore

    mem = InMemoryBackend()
    PerPluginStore("wet", None, backend=mem, sub_key="tokens/drive").save(
        {"refresh_token": "xyz"}
    )
    assert load_token("drive", backend=mem) is None


def test_load_backend_error_returns_none(token_dir):
    """load_token swallows backend errors and returns None (re-auth, not crash)."""

    class _BoomBackend:
        def get(self, key):
            raise OSError("disk error")

        def put(self, key, blob):
            raise OSError("disk error")

        def delete(self, key):
            raise OSError("disk error")

    assert load_token("drive", backend=_BoomBackend()) is None


def test_save_token_creates_dir(token_dir, tmp_path):
    """save_token creates the LocalFs token dir if it doesn't exist."""
    save_token("s3", {"access_token": "abc"})
    assert (tmp_path / ".wet-mcp" / "tokens" / "s3.json").exists()


def test_get_token_dir_for_sub(token_dir, tmp_path):
    """Test _get_token_dir_for_sub helper."""
    assert _get_token_dir_for_sub("user1") == tmp_path / "subs" / "user1" / "tokens"


def test_get_token_path_for_sub(token_dir, tmp_path):
    """Test get_token_path_for_sub returns correct scoped path."""
    expected = tmp_path / "subs" / "user1" / "tokens" / "drive.json"
    assert get_token_path_for_sub("user1", "drive") == expected


def test_save_and_load_token_for_sub(token_dir, tmp_path):
    """Test standard save and load flow for per-sub tokens (encrypted blob)."""
    sub = "user123"
    token = {"access_token": "sub-token-456", "token_type": "Bearer"}

    save_token_for_sub(sub, "drive", token)
    loaded = load_token_for_sub(sub, "drive")

    assert loaded == token
    # Encrypted token landed under the per-sub LocalFs layout.
    assert (tmp_path / ".wet-mcp" / "subs" / sub / "tokens" / "drive.json").exists()


def test_load_token_for_sub_missing(token_dir):
    """load_token_for_sub returns None if file doesn't exist."""
    assert load_token_for_sub("no-user", "drive") is None


def test_load_token_for_sub_invalid_format(token_dir, tmp_path):
    """load_token_for_sub returns None when the stored blob is undecryptable."""
    sub = "user1"
    path = tmp_path / ".wet-mcp" / "subs" / sub / "tokens" / "drive.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"not a valid aes-gcm blob")
    assert load_token_for_sub(sub, "drive") is None


def test_read_token_for_sub_alias():
    """Verify read_token_for_sub is an alias for load_token_for_sub."""
    assert read_token_for_sub is load_token_for_sub


def test_load_token_for_sub_non_dict(token_dir):
    """load_token_for_sub returns None if the decrypted payload is not a dict."""
    from mcp_core.storage.backends import InMemoryBackend
    from mcp_core.storage.per_plugin_store import PerPluginStore

    mem = InMemoryBackend()
    store = PerPluginStore("wet", "user1", backend=mem, sub_key="tokens/drive")
    non_dict_payload: object = [1, 2, 3]
    store.save(non_dict_payload)  # type: ignore
    assert load_token_for_sub("user1", "drive", backend=mem) is None


def test_load_token_for_sub_backend_error_returns_none(token_dir):
    """load_token_for_sub swallows backend errors and returns None."""

    class _BoomBackend:
        def get(self, key):
            raise OSError("disk error")

        def put(self, key, blob):
            raise OSError("disk error")

        def delete(self, key):
            raise OSError("disk error")

    assert load_token_for_sub("user1", "drive", backend=_BoomBackend()) is None


def test_get_token_path_for_sub_simple_assertion(token_dir, tmp_path):
    """Simple assertion matching the output path for get_token_path_for_sub."""
    sub = "test-user"
    provider = "google"
    expected = tmp_path / "subs" / sub / "tokens" / f"{provider}.json"
    result = get_token_path_for_sub(sub, provider)
    assert result == expected


def test_get_token_path_standard(token_dir):
    """Test get_token_path with standard provider strings."""
    for provider in ["google", "github", "slack"]:
        assert get_token_path(provider) == token_dir / f"{provider}.json"


def test_path_traversal_validation_empty_sub(token_dir):
    """Test that empty sub is blocked in get_token_path_for_sub."""
    with pytest.raises(ValueError, match="Name cannot be empty"):
        get_token_path_for_sub("", "drive")
