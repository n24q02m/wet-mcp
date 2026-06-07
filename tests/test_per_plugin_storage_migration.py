"""Verify migration to PerPluginStore + cred persistence works.

These tests verify that credential_state.py and relay_setup.py read and write
through mcp_core.storage.per_plugin_store.PerPluginStore("wet", ...) rather
than the deprecated mcp_core.storage.config_file shared store.
"""

from unittest.mock import patch


def test_loads_from_new_path(tmp_path, monkeypatch):
    """After migration, resolve_credential_state reads from PerPluginStore.

    Per spec 2026-05-01-stdio-pure-http-multiuser.md §4.1 + OQ3, the
    PerPluginStore fallback only fires in HTTP mode (stdio reads env vars
    ONLY). This test exercises the HTTP-mode persistence path.
    """
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)

    # Clear all cloud-key env vars so resolve falls through to store
    from wet_mcp.credential_state import CLOUD_KEYS

    for k in CLOUD_KEYS:
        monkeypatch.delenv(k, raising=False)

    # Mark HTTP mode so the per-plugin store fallback path is exercised.
    monkeypatch.setenv("MCP_TRANSPORT", "http")

    # Pre-populate via PerPluginStore
    from mcp_core.storage.per_plugin_store import PerPluginStore

    PerPluginStore("wet").save(
        {"GEMINI_API_KEY": "fake-key", "JINA_AI_API_KEY": "fake-jina"}
    )

    # resolve_credential_state should detect the stored credentials
    import wet_mcp.credential_state as mod

    mod._state = mod.CredentialState.AWAITING_SETUP

    with patch("mcp_core.get_mode", return_value=None):
        result = mod.resolve_credential_state()

    assert result == mod.CredentialState.CONFIGURED
    # env vars applied from stored creds
    assert mod.os.environ.get("GEMINI_API_KEY") == "fake-key"


def test_save_writes_to_new_path(tmp_path, monkeypatch):
    """After migration, save_credentials writes to PerPluginStore."""
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)

    from wet_mcp.credential_state import save_credentials

    with (
        patch("wet_mcp.relay_setup.apply_config"),
        patch("wet_mcp.config.settings") as mock_settings,
    ):
        mock_settings.google_drive_client_id = ""
        mock_settings.google_drive_client_secret = ""
        mock_settings.setup_providers = lambda: None
        save_credentials({"GEMINI_API_KEY": "saved-key"}, {"sub": "local-user"})

    from mcp_core.storage.per_plugin_store import PerPluginStore

    creds = PerPluginStore("wet").load()
    assert creds is not None
    assert creds.get("GEMINI_API_KEY") == "saved-key"


def test_clear_removes_new_path(tmp_path, monkeypatch):
    """After migration, reset_state clears PerPluginStore."""
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)

    # Write something first
    from mcp_core.storage.per_plugin_store import PerPluginStore

    PerPluginStore("wet").save({"x": "y"})

    # reset_state should clear it
    from wet_mcp.credential_state import reset_state

    with patch("mcp_core.clear_mode"):
        reset_state()

    assert PerPluginStore("wet").load() is None


def test_no_config_file_import_in_credential_state():
    """credential_state.py must not import from mcp_core.storage.config_file at module level."""
    import ast
    import pathlib

    src = (
        pathlib.Path(__file__).parent.parent / "src" / "wet_mcp" / "credential_state.py"
    )
    tree = ast.parse(src.read_text())

    for node in ast.walk(tree):
        # Check top-level imports only (not inside functions)
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            if isinstance(node, ast.ImportFrom) and node.module:
                assert "config_file" not in node.module, (
                    f"Top-level import from config_file found at line {node.lineno}. "
                    "credential_state.py must use PerPluginStore exclusively."
                )
