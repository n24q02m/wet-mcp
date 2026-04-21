"""Tests for wet_mcp.credential_state -- non-blocking credential state machine."""

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from wet_mcp.credential_state import (
    CLOUD_KEYS,
    SERVER_NAME,
    CredentialState,
    get_setup_url,
    get_state,
    reset_state,
    resolve_credential_state,
    set_state,
    trigger_relay_setup,
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


class TestGetState:
    """Tests for get_state and get_setup_url."""

    def test_default_state(self):
        assert get_state() == CredentialState.AWAITING_SETUP

    def test_default_setup_url(self):
        assert get_setup_url() is None


class TestSetState:
    """Tests for set_state."""

    def test_set_configured(self):
        set_state(CredentialState.CONFIGURED)
        assert get_state() == CredentialState.CONFIGURED

    def test_set_local(self):
        set_state(CredentialState.LOCAL)
        assert get_state() == CredentialState.LOCAL

    def test_set_setup_in_progress(self):
        set_state(CredentialState.SETUP_IN_PROGRESS)
        assert get_state() == CredentialState.SETUP_IN_PROGRESS


class TestResolveCredentialState:
    """Tests for resolve_credential_state."""

    def test_env_vars_configured(self, monkeypatch):
        """When env vars have cloud keys, state = CONFIGURED."""
        monkeypatch.setenv("GEMINI_API_KEY", "test-key")
        result = resolve_credential_state()
        assert result == CredentialState.CONFIGURED
        assert get_state() == CredentialState.CONFIGURED

    def test_env_vars_jina(self, monkeypatch):
        """JINA_AI_API_KEY also triggers CONFIGURED."""
        for k in CLOUD_KEYS:
            monkeypatch.delenv(k, raising=False)
        monkeypatch.setenv("JINA_AI_API_KEY", "jina_test")
        result = resolve_credential_state()
        assert result == CredentialState.CONFIGURED

    def test_config_file_configured(self, monkeypatch):
        """When config file has cloud keys, apply to env and state = CONFIGURED."""
        for k in CLOUD_KEYS:
            monkeypatch.delenv(k, raising=False)

        saved = {"GEMINI_API_KEY": "from-file", "OPENAI_API_KEY": ""}
        with patch(
            "mcp_core.storage.config_file.read_config",
            return_value=saved,
        ):
            result = resolve_credential_state()
            assert result == CredentialState.CONFIGURED
            assert os.environ.get("GEMINI_API_KEY") == "from-file"
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    def test_config_file_no_cloud_keys(self, monkeypatch):
        """Config file without cloud keys does NOT set CONFIGURED."""
        for k in CLOUD_KEYS:
            monkeypatch.delenv(k, raising=False)

        saved = {"SOME_OTHER_KEY": "value"}
        with (
            patch(
                "mcp_core.storage.config_file.read_config",
                return_value=saved,
            ),
            patch(
                "mcp_core.get_mode",
                return_value=None,
            ),
        ):
            result = resolve_credential_state()
            assert result == CredentialState.AWAITING_SETUP

    def test_config_file_read_error(self, monkeypatch):
        """Config file read error falls through gracefully."""
        for k in CLOUD_KEYS:
            monkeypatch.delenv(k, raising=False)

        with (
            patch(
                "mcp_core.storage.config_file.read_config",
                side_effect=Exception("decrypt failed"),
            ),
            patch(
                "mcp_core.get_mode",
                return_value=None,
            ),
        ):
            result = resolve_credential_state()
            assert result == CredentialState.AWAITING_SETUP

    def test_local_mode_marker(self, monkeypatch):
        """When local mode marker is set, state = LOCAL."""
        for k in CLOUD_KEYS:
            monkeypatch.delenv(k, raising=False)

        with (
            patch(
                "mcp_core.storage.config_file.read_config",
                return_value=None,
            ),
            patch(
                "mcp_core.get_mode",
                return_value="local",
            ),
        ):
            result = resolve_credential_state()
            assert result == CredentialState.LOCAL

    def test_local_mode_error_fallthrough(self, monkeypatch):
        """get_mode error falls through to AWAITING_SETUP."""
        for k in CLOUD_KEYS:
            monkeypatch.delenv(k, raising=False)

        with (
            patch(
                "mcp_core.storage.config_file.read_config",
                return_value=None,
            ),
            patch(
                "mcp_core.get_mode",
                side_effect=Exception("file not found"),
            ),
        ):
            result = resolve_credential_state()
            assert result == CredentialState.AWAITING_SETUP

    def test_nothing_found(self, monkeypatch):
        """When nothing is found, state = AWAITING_SETUP."""
        for k in CLOUD_KEYS:
            monkeypatch.delenv(k, raising=False)

        with (
            patch(
                "mcp_core.storage.config_file.read_config",
                return_value=None,
            ),
            patch(
                "mcp_core.get_mode",
                return_value=None,
            ),
        ):
            result = resolve_credential_state()
            assert result == CredentialState.AWAITING_SETUP


class TestTriggerRelaySetup:
    """Tests for trigger_relay_setup -- local HTTP fallback (no remote relay)."""

    async def test_skips_when_configured(self):
        """Does not trigger when already CONFIGURED."""
        set_state(CredentialState.CONFIGURED)
        result = await trigger_relay_setup()
        assert result is None  # No URL since no setup_url was set

    async def test_skips_when_local(self):
        """Does not trigger when LOCAL."""
        set_state(CredentialState.LOCAL)
        result = await trigger_relay_setup()
        assert result is None

    async def test_force_spawns_local_form(self):
        """force=True spawns a local credential form even when CONFIGURED."""
        set_state(CredentialState.CONFIGURED)
        mock_handle = MagicMock(host="127.0.0.1", port=52001)

        with (
            patch(
                "mcp_core.start_local_server_background",
                new_callable=AsyncMock,
                return_value=mock_handle,
                create=True,
            ) as mock_start,
            patch("mcp_core.try_open_browser", return_value=True),
        ):
            result = await trigger_relay_setup(force=True)
            assert result == "http://127.0.0.1:52001/"
            assert get_state() == CredentialState.SETUP_IN_PROGRESS
            mock_start.assert_awaited_once()

    async def test_reuses_active_handle(self):
        """If an active handle already exists, reuse its URL."""
        import wet_mcp.credential_state as mod

        mod._state = CredentialState.AWAITING_SETUP
        mod._active_handle = MagicMock()
        mod._setup_url = "http://127.0.0.1:52002/"

        with patch(
            "mcp_core.start_local_server_background",
            new_callable=AsyncMock,
            create=True,
        ) as mock_start:
            result = await trigger_relay_setup()
            assert result == "http://127.0.0.1:52002/"
            mock_start.assert_not_awaited()

        mod._active_handle = None

    async def test_creates_new_spawn(self):
        """AWAITING_SETUP with no handle -> spawn local form, open browser."""
        mock_handle = MagicMock(host="127.0.0.1", port=52003)

        with (
            patch(
                "mcp_core.start_local_server_background",
                new_callable=AsyncMock,
                return_value=mock_handle,
                create=True,
            ) as mock_start,
            patch("mcp_core.try_open_browser", return_value=True) as mock_browser,
        ):
            result = await trigger_relay_setup()
            assert result == "http://127.0.0.1:52003/"
            mock_start.assert_awaited_once()
            call_kwargs = mock_start.await_args.kwargs
            assert call_kwargs["server_name"] == SERVER_NAME
            assert call_kwargs["host"] == "127.0.0.1"
            assert call_kwargs["port"] == 0
            mock_browser.assert_called_once_with("http://127.0.0.1:52003/")

    async def test_exception_returns_none(self):
        """On spawn failure, returns None and resets to AWAITING_SETUP."""
        with patch(
            "mcp_core.start_local_server_background",
            new_callable=AsyncMock,
            side_effect=RuntimeError("bind failed"),
            create=True,
        ):
            result = await trigger_relay_setup()
            assert result is None
            assert get_state() == CredentialState.AWAITING_SETUP


class TestResetState:
    """Tests for reset_state."""

    def test_resets_to_awaiting_setup(self):
        set_state(CredentialState.CONFIGURED)
        import wet_mcp.credential_state as mod

        mod._setup_url = "https://example.com"

        with (
            patch("mcp_core.clear_mode"),
            patch("mcp_core.storage.config_file.delete_config"),
        ):
            reset_state()
            assert get_state() == CredentialState.AWAITING_SETUP
            assert get_setup_url() is None

    def test_reset_handles_errors(self):
        """reset_state handles errors gracefully."""
        set_state(CredentialState.CONFIGURED)
        with (
            patch("mcp_core.clear_mode", side_effect=Exception("fail")),
        ):
            reset_state()
            assert get_state() == CredentialState.AWAITING_SETUP


class TestServerSetupToolNewActions:
    """Tests for setup_* actions in config tool (setup_status, setup_skip, setup_reset, etc.)."""

    async def test_status_action(self, monkeypatch):
        """setup_status action returns current state."""
        import json

        from wet_mcp.server import config

        set_state(CredentialState.CONFIGURED)
        monkeypatch.setenv("GEMINI_API_KEY", "test")
        result = await config(action="setup_status")
        data = json.loads(result)
        assert data["state"] == "configured"
        assert "GEMINI_API_KEY" in data["cloud_keys_in_env"]

    async def test_start_action_when_configured(self):
        """setup_open_relay returns error when CONFIGURED and no force (relay skips)."""
        import json

        from wet_mcp.server import config

        set_state(CredentialState.CONFIGURED)
        result = await config(action="setup_open_relay")
        data = json.loads(result)
        assert data["status"] == "error"

    async def test_start_action_force(self):
        """setup_open_relay with force triggers relay."""
        import json

        from wet_mcp.server import config

        set_state(CredentialState.CONFIGURED)
        with patch(
            "wet_mcp.credential_state.trigger_relay_setup",
            new_callable=AsyncMock,
            return_value="https://relay.example.com/setup/abc",
        ):
            result = await config(action="setup_open_relay", force=True)
            data = json.loads(result)
            assert data["status"] == "relay_started"
            assert data["setup_url"] == "https://relay.example.com/setup/abc"

    async def test_start_action_failure(self):
        """setup_open_relay returns error when relay fails."""
        import json

        from wet_mcp.server import config

        set_state(CredentialState.AWAITING_SETUP)
        with patch(
            "wet_mcp.credential_state.trigger_relay_setup",
            new_callable=AsyncMock,
            return_value=None,
        ):
            result = await config(action="setup_open_relay")
            data = json.loads(result)
            assert data["status"] == "error"

    async def test_skip_action(self):
        """setup_skip action sets LOCAL mode."""
        import json

        from wet_mcp.server import config

        with patch("mcp_core.set_local_mode") as mock_set:
            result = await config(action="setup_skip")
            data = json.loads(result)
            assert data["status"] == "ok"
            assert get_state() == CredentialState.LOCAL
            mock_set.assert_called_once_with("wet-mcp")

    async def test_reset_action(self):
        """setup_reset action clears state."""
        import json

        from wet_mcp.server import config

        set_state(CredentialState.CONFIGURED)
        with (
            patch("mcp_core.clear_mode"),
            patch("mcp_core.storage.config_file.delete_config"),
        ):
            result = await config(action="setup_reset")
            data = json.loads(result)
            assert data["status"] == "ok"
            assert get_state() == CredentialState.AWAITING_SETUP

    async def test_invalid_action_suggests(self):
        """Invalid action includes fuzzy match suggestion."""
        import json

        from wet_mcp.server import config

        result = await config(action="setup_statu")
        data = json.loads(result)
        assert "error" in data
        assert "setup_status" in data["error"]  # fuzzy match suggestion

    async def test_complete_action_refreshes_state(self, monkeypatch):
        """setup_complete action re-resolves credentials and transitions to CONFIGURED."""
        import json

        from wet_mcp.server import config

        set_state(CredentialState.AWAITING_SETUP)
        monkeypatch.setenv("GEMINI_API_KEY", "test-complete-key")
        with patch("wet_mcp.server.settings") as mock_settings:
            mock_settings.setup_providers = MagicMock()
            result = await config(action="setup_complete")
            data = json.loads(result)
            assert data["status"] == "ok"
            assert data["state"] == "configured"
            assert data["message"] == "Credential state refreshed."
            mock_settings.setup_providers.assert_called_once()


class TestShareCloudKeysToPeers:
    """Tests for _share_cloud_keys_to_peers helper."""

    def test_shares_cloud_keys(self):
        """Shares matching cloud keys to peer servers."""
        from wet_mcp.credential_state import _share_cloud_keys_to_peers

        config = {"GEMINI_API_KEY": "test-key", "SOME_OTHER": "val"}
        with patch("mcp_core.storage.config_file.write_config") as mock_write:
            _share_cloud_keys_to_peers(config)
            assert mock_write.call_count == 2
            # Should write to both peers
            calls = [c.args[0] for c in mock_write.call_args_list]
            assert "mnemo-mcp" in calls
            assert "better-code-review-graph" in calls

    def test_skips_when_no_cloud_keys(self):
        """Skips when config has no matching cloud keys."""
        from wet_mcp.credential_state import _share_cloud_keys_to_peers

        config = {"SOME_KEY": "value"}
        with patch("mcp_core.storage.config_file.write_config") as mock_write:
            _share_cloud_keys_to_peers(config)
            mock_write.assert_not_called()

    def test_handles_write_error(self):
        """Handles write_config error for individual peer and continues."""
        from wet_mcp.credential_state import _share_cloud_keys_to_peers

        config = {"OPENAI_API_KEY": "test-key"}

        def side_effect(peer, shared):
            if peer == "mnemo-mcp":
                raise RuntimeError("mnemo failed")
            return None

        with patch(
            "mcp_core.storage.config_file.write_config",
            side_effect=side_effect,
        ) as mock_write:
            # Should not raise
            _share_cloud_keys_to_peers(config)
            # Should still attempt both peers
            assert mock_write.call_count == 2

    def test_handles_import_error(self):
        """Handles import error gracefully."""
        from wet_mcp.credential_state import _share_cloud_keys_to_peers

        config = {"GEMINI_API_KEY": "test-key"}
        with patch(
            "mcp_core.storage.config_file.write_config",
            side_effect=ImportError("no module"),
        ):
            _share_cloud_keys_to_peers(config)


class TestRequireCredentials:
    """Tests for _require_credentials helper."""

    def test_returns_error_json_when_awaiting_setup(self):
        """Returns error JSON when state is AWAITING_SETUP."""
        import json

        import wet_mcp.credential_state as mod
        from wet_mcp.server import _require_credentials

        set_state(CredentialState.AWAITING_SETUP)
        mod._setup_url = "https://relay.example.com/setup/abc"
        result = _require_credentials()
        assert result is not None
        data = json.loads(result)
        assert data["error"] == "Credentials not configured"
        assert data["state"] == "awaiting_setup"
        assert data["setup_url"] == "https://relay.example.com/setup/abc"
        assert "open_relay" in data["instructions"]
        assert "set_env" not in data["instructions"]

    def test_returns_none_when_configured(self):
        """Returns None when state is CONFIGURED."""
        from wet_mcp.server import _require_credentials

        set_state(CredentialState.CONFIGURED)
        result = _require_credentials()
        assert result is None

    def test_returns_error_json_with_null_url_when_no_relay_session(self):
        """Returns error JSON with null setup_url when relay not yet started."""
        import json

        from wet_mcp.server import _require_credentials

        set_state(CredentialState.AWAITING_SETUP)
        # _setup_url is already None (reset by _reset_module_state fixture)
        result = _require_credentials()
        assert result is not None
        data = json.loads(result)
        assert data["setup_url"] is None


class TestSaveCredentialsGdriveNextStep:
    """Cover the GDrive Device Code branch in save_credentials, including
    the best-effort try_open_browser launch at the verification URL."""

    def test_returns_device_code_and_opens_browser(self):
        from wet_mcp.credential_state import save_credentials

        device_payload = {
            "device_code": "dev123",
            "user_code": "USER-CODE",
            "verification_url": "https://example.test/verify",
            "interval": 5,
            "expires_in": 1800,
        }

        mock_httpx_response = MagicMock()
        mock_httpx_response.status_code = 200
        mock_httpx_response.json = MagicMock(return_value=device_payload)

        with (
            patch("mcp_core.storage.config_file.write_config"),
            patch("wet_mcp.relay_setup.apply_config"),
            patch("wet_mcp.credential_state._share_cloud_keys_to_peers"),
            patch("wet_mcp.config.settings") as mock_settings,
            patch("httpx.post", return_value=mock_httpx_response),
            patch("threading.Thread") as mock_thread,
            patch("mcp_core.try_open_browser") as mock_browser,
        ):
            mock_settings.google_drive_client_id = "cid"
            mock_settings.google_drive_client_secret = "csec"
            mock_settings.setup_providers = MagicMock()

            result = save_credentials({"FOO": "bar"})

        assert result is not None
        assert result["type"] == "oauth_device_code"
        assert result["verification_url"] == "https://example.test/verify"
        assert result["user_code"] == "USER-CODE"
        mock_browser.assert_called_once_with("https://example.test/verify")
        mock_thread.assert_called_once()

    def test_returns_none_when_device_code_non_200(self):
        from wet_mcp.credential_state import save_credentials

        mock_httpx_response = MagicMock()
        mock_httpx_response.status_code = 400
        mock_httpx_response.json = MagicMock(return_value={})

        with (
            patch("mcp_core.storage.config_file.write_config"),
            patch("wet_mcp.relay_setup.apply_config"),
            patch("wet_mcp.credential_state._share_cloud_keys_to_peers"),
            patch("wet_mcp.config.settings") as mock_settings,
            patch("httpx.post", return_value=mock_httpx_response),
        ):
            mock_settings.google_drive_client_id = "cid"
            mock_settings.google_drive_client_secret = "csec"
            mock_settings.setup_providers = MagicMock()

            result = save_credentials({"FOO": "bar"})

        assert result is None

    def test_returns_none_when_no_gdrive_configured(self):
        from wet_mcp.credential_state import save_credentials

        with (
            patch("mcp_core.storage.config_file.write_config"),
            patch("wet_mcp.relay_setup.apply_config"),
            patch("wet_mcp.credential_state._share_cloud_keys_to_peers"),
            patch("wet_mcp.config.settings") as mock_settings,
        ):
            mock_settings.google_drive_client_id = ""
            mock_settings.google_drive_client_secret = ""
            mock_settings.setup_providers = MagicMock()

            result = save_credentials({"FOO": "bar"})

        assert result is None

    def test_provider_reinit_failure_non_fatal(self):
        """save_credentials swallows provider re-init errors."""
        from wet_mcp.credential_state import save_credentials

        with (
            patch("mcp_core.storage.config_file.write_config"),
            patch("wet_mcp.relay_setup.apply_config"),
            patch("wet_mcp.credential_state._share_cloud_keys_to_peers"),
            patch("wet_mcp.config.settings") as mock_settings,
        ):
            mock_settings.setup_providers = MagicMock(
                side_effect=RuntimeError("init failed")
            )
            mock_settings.google_drive_client_id = ""
            mock_settings.google_drive_client_secret = ""
            # Should not raise
            result = save_credentials({"FOO": "bar"})
            assert result is None

    def test_poll_thread_target(self):
        """Cover the internal _poll_gdrive_token function used as thread target."""
        from wet_mcp.credential_state import save_credentials

        device_payload = {
            "device_code": "dev123",
            "user_code": "USER-CODE",
            "verification_url": "https://example.test/verify",
            "interval": 5,
            "expires_in": 1800,
        }
        mock_httpx_response = MagicMock()
        mock_httpx_response.status_code = 200
        mock_httpx_response.json = MagicMock(return_value=device_payload)

        with (
            patch("mcp_core.storage.config_file.write_config"),
            patch("wet_mcp.relay_setup.apply_config"),
            patch("wet_mcp.credential_state._share_cloud_keys_to_peers"),
            patch("wet_mcp.config.settings") as mock_settings,
            patch("httpx.post", return_value=mock_httpx_response),
            patch("threading.Thread") as mock_thread,
            patch("asyncio.run") as mock_run,
            patch("wet_mcp.credential_state._gdrive_token_poll"),
        ):
            mock_settings.google_drive_client_id = "cid"
            mock_settings.google_drive_client_secret = "csec"
            mock_settings.setup_providers = MagicMock()

            save_credentials({"FOO": "bar"})

            # Capture the target function
            target = mock_thread.call_args.kwargs["target"]
            # It should call asyncio.run(_gdrive_token_poll(...))
            # Use a normal MagicMock for _gdrive_token_poll instead of AsyncMock (default in some contexts)
            # to avoid RuntimeWarnings since we aren't actually running it with asyncio.
            with patch(
                "wet_mcp.credential_state._gdrive_token_poll", new=MagicMock()
            ) as mock_poll_sync:
                target()
                mock_poll_sync.assert_called_once_with("cid", "csec", "dev123", 5, 1800)

            mock_run.assert_called_once()

    def test_device_code_request_exception_non_fatal(self):
        """save_credentials swallows httpx.post exceptions for device code."""
        from wet_mcp.credential_state import save_credentials

        with (
            patch("mcp_core.storage.config_file.write_config"),
            patch("wet_mcp.relay_setup.apply_config"),
            patch("wet_mcp.credential_state._share_cloud_keys_to_peers"),
            patch("wet_mcp.config.settings") as mock_settings,
            patch("httpx.post", side_effect=ConnectionError("oauth down")),
        ):
            mock_settings.google_drive_client_id = "cid"
            mock_settings.google_drive_client_secret = "csec"
            mock_settings.setup_providers = MagicMock()
            result = save_credentials({"FOO": "bar"})
            assert result is None


class TestSetGdriveCompleteCallback:
    def test_callback_registration(self):
        """set_gdrive_complete_callback stores the callback and logs."""
        import wet_mcp.credential_state as mod
        from wet_mcp.credential_state import set_gdrive_complete_callback

        def cb():
            pass

        with patch("wet_mcp.credential_state.logger") as mock_logger:
            set_gdrive_complete_callback(cb)
            mock_logger.debug.assert_called_with("GDrive complete callback registered")

        assert mod._on_gdrive_complete is cb
        # cleanup
        mod._on_gdrive_complete = None


class TestSetGdriveFailedCallback:
    """Failure callback wires into mcp-core's ``mark_setup_failed``.

    Without this, a Google device-code terminal error (invalid_grant /
    expired_token / access_denied) left the browser spinner waiting
    forever because the server only knew ``idle`` / ``complete`` states.
    """

    def test_failed_callback_registration(self):
        import wet_mcp.credential_state as mod
        from wet_mcp.credential_state import (
            _reset_callbacks_for_test,
            set_gdrive_failed_callback,
        )

        _reset_callbacks_for_test()

        def cb(key: str, error: str) -> None:
            pass

        with patch("wet_mcp.credential_state.logger") as mock_logger:
            set_gdrive_failed_callback(cb)
            mock_logger.debug.assert_called_with("GDrive failed callback registered")

        assert mod._on_gdrive_failed is cb
        _reset_callbacks_for_test()

    def test_wire_callbacks_sets_both(self):
        """wire_gdrive_callbacks populates BOTH complete + failed handlers."""
        import wet_mcp.credential_state as mod
        from wet_mcp.credential_state import (
            _reset_callbacks_for_test,
            wire_gdrive_callbacks,
        )

        _reset_callbacks_for_test()

        complete_calls: list[str] = []
        failed_calls: list[tuple[str, str]] = []

        def mark_complete(key: str = "gdrive") -> None:
            complete_calls.append(key)

        def mark_failed(key: str = "gdrive", error: str = "?") -> None:
            failed_calls.append((key, error))

        wire_gdrive_callbacks(mark_complete, mark_failed)

        # The complete callback is wrapped to also schedule spawn cleanup,
        # so we verify invocation semantics rather than identity.
        failed_cb = mod._on_gdrive_failed
        complete_cb = mod._on_gdrive_complete
        assert failed_cb is not None
        assert complete_cb is not None

        failed_cb("gdrive", "invalid_grant")
        assert failed_calls == [("gdrive", "invalid_grant")]

        complete_cb()
        assert complete_calls == ["gdrive"]

        _reset_callbacks_for_test()

    def test_wire_callbacks_adapter_swallows_exception(self):
        """mark_failed raising should not crash the poll loop."""
        import wet_mcp.credential_state as mod
        from wet_mcp.credential_state import (
            _reset_callbacks_for_test,
            wire_gdrive_callbacks,
        )

        _reset_callbacks_for_test()

        def mark_complete(key: str = "gdrive") -> None:
            pass

        def mark_failed(key: str = "gdrive", error: str = "?") -> None:
            raise RuntimeError("boom")

        wire_gdrive_callbacks(mark_complete, mark_failed)
        # Must not raise.
        cb = mod._on_gdrive_failed
        assert cb is not None
        cb("gdrive", "invalid_grant")

        _reset_callbacks_for_test()

    def test_wire_callbacks_legacy_1arg_only_wires_complete(self):
        """Legacy mcp-core (<1.3.0) calls ``hook(mark_complete)`` with one arg.

        ``wire_gdrive_callbacks`` must still work: the complete callback
        gets wired, the failed callback stays None, and the code degrades
        to log-only on Google terminal errors (legacy behavior).
        """
        import wet_mcp.credential_state as mod
        from wet_mcp.credential_state import (
            _reset_callbacks_for_test,
            wire_gdrive_callbacks,
        )

        _reset_callbacks_for_test()

        complete_calls: list[str] = []

        def mark_complete(key: str = "gdrive") -> None:
            complete_calls.append(key)

        # Simulate legacy arity: call with mark_complete only, no mark_failed.
        wire_gdrive_callbacks(mark_complete)
        # Complete callback is wrapped (adds spawn cleanup); verify invocation
        # reaches mark_complete rather than identity.
        assert mod._on_gdrive_complete is not None
        mod._on_gdrive_complete()
        assert complete_calls == ["gdrive"]
        assert mod._on_gdrive_failed is None

        _reset_callbacks_for_test()


class TestShareCloudKeysOuterException:
    def test_outer_import_error_non_fatal(self):
        """Outer ImportError for write_config should be swallowed."""
        import builtins

        from wet_mcp.credential_state import _share_cloud_keys_to_peers

        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name == "mcp_core.storage.config_file":
                raise ImportError("no mcp_core")
            return real_import(name, *args, **kwargs)

        with patch.object(builtins, "__import__", side_effect=fake_import):
            # Should not raise
            _share_cloud_keys_to_peers({"GEMINI_API_KEY": "key"})

    def test_outer_exception_swallowed(self):
        """Broad Exception in outer block should be swallowed."""
        from wet_mcp.credential_state import _share_cloud_keys_to_peers

        # Passing None as config triggers AttributeError in shared = {...}
        with patch("mcp_core.storage.config_file.write_config"):
            _share_cloud_keys_to_peers(None)  # type: ignore


class TestGdriveTokenPoll:
    """Cover _gdrive_token_poll success / slow_down / error / expiry branches."""

    async def _run_poll(self, responses):
        """Helper: run _gdrive_token_poll with a sequence of mock responses."""
        from wet_mcp.credential_state import _gdrive_token_poll

        class _FakeResp:
            def __init__(self, data):
                self._data = data

            def json(self):
                return self._data

        it = iter(responses)

        async def fake_post(*a, **kw):
            try:
                return _FakeResp(next(it))
            except StopIteration:
                return _FakeResp({"error": "authorization_pending"})

        class _FakeClient:
            def __init__(self, *a, **kw):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def post(self, *a, **kw):
                return await fake_post(*a, **kw)

        async def fake_sleep(_):
            return None

        with (
            patch("httpx.AsyncClient", _FakeClient),
            patch("asyncio.sleep", new=fake_sleep),
        ):
            await _gdrive_token_poll("cid", "csec", "devcode", 1, 1)

    async def test_success_saves_token_and_calls_callback(self):
        import wet_mcp.credential_state as mod
        from wet_mcp.credential_state import set_gdrive_complete_callback

        cb_called = []
        set_gdrive_complete_callback(lambda: cb_called.append(True))
        try:
            with patch("wet_mcp.token_store.save_token") as mock_save:
                await self._run_poll(
                    [{"access_token": "tok-abc", "refresh_token": "r"}]
                )
                mock_save.assert_called_once()
                assert cb_called == [True]
        finally:
            mod._on_gdrive_complete = None

    async def test_success_callback_exception_non_fatal(self):
        import wet_mcp.credential_state as mod
        from wet_mcp.credential_state import set_gdrive_complete_callback

        def bad_cb():
            raise RuntimeError("cb died")

        set_gdrive_complete_callback(bad_cb)
        try:
            with patch("wet_mcp.token_store.save_token"):
                await self._run_poll([{"access_token": "tok-abc"}])
        finally:
            mod._on_gdrive_complete = None

    async def test_slow_down_increases_interval(self):
        # slow_down then success
        with patch("wet_mcp.token_store.save_token") as mock_save:
            await self._run_poll(
                [
                    {"error": "slow_down"},
                    {"access_token": "tok"},
                ]
            )
            mock_save.assert_called_once()

    async def test_generic_error_returns(self):
        # unknown error returns without saving
        with patch("wet_mcp.token_store.save_token") as mock_save:
            await self._run_poll([{"error": "access_denied"}])
            mock_save.assert_not_called()

    async def test_terminal_error_invokes_failed_callback(self):
        """Google terminal error must fire _on_gdrive_failed so the browser stops polling.

        Without this, the credential form's spinner waited forever on
        "Waiting for authorization..." even though the backend had given up.
        """
        from wet_mcp.credential_state import (
            _reset_callbacks_for_test,
            set_gdrive_failed_callback,
        )

        _reset_callbacks_for_test()
        calls: list[tuple[str, str]] = []

        def on_fail(key: str, error: str) -> None:
            calls.append((key, error))

        set_gdrive_failed_callback(on_fail)
        try:
            with patch("wet_mcp.token_store.save_token") as mock_save:
                await self._run_poll(
                    [
                        {
                            "error": "invalid_grant",
                            "error_description": "Bad device code",
                        }
                    ]
                )
                mock_save.assert_not_called()
            assert len(calls) == 1
            assert calls[0][0] == "gdrive"
            assert "Bad device code" in calls[0][1]
        finally:
            _reset_callbacks_for_test()

    async def test_terminal_error_without_description_uses_error_code(self):
        """If Google omits error_description, fall back to error code."""
        from wet_mcp.credential_state import (
            _reset_callbacks_for_test,
            set_gdrive_failed_callback,
        )

        _reset_callbacks_for_test()
        calls: list[tuple[str, str]] = []
        set_gdrive_failed_callback(lambda k, e: calls.append((k, e)))
        try:
            with patch("wet_mcp.token_store.save_token"):
                await self._run_poll([{"error": "access_denied"}])
            assert calls == [("gdrive", "access_denied")]
        finally:
            _reset_callbacks_for_test()

    async def test_deadline_expiry_invokes_failed_callback(self):
        """Loop expiring without success -> failed callback with 'expired'."""
        from wet_mcp.credential_state import (
            _gdrive_token_poll,
            _reset_callbacks_for_test,
            set_gdrive_failed_callback,
        )

        _reset_callbacks_for_test()
        calls: list[tuple[str, str]] = []
        set_gdrive_failed_callback(lambda k, e: calls.append((k, e)))

        class _NoopClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def post(self, *a, **kw):
                class R:
                    def json(self):
                        return {"error": "authorization_pending"}

                return R()

        async def fake_sleep(_):
            return None

        try:
            with (
                patch("httpx.AsyncClient", _NoopClient),
                patch("asyncio.sleep", new=fake_sleep),
            ):
                # expires_in=0 makes deadline immediate so the loop never
                # iterates and we fall through to the expiry path.
                await _gdrive_token_poll("cid", "csec", "dev", 0, 0)
            assert calls == [("gdrive", "expired")]
        finally:
            _reset_callbacks_for_test()

    async def test_terminal_error_no_callback_registered_is_safe(self):
        """Missing failed callback must not crash the poll."""
        from wet_mcp.credential_state import _reset_callbacks_for_test

        _reset_callbacks_for_test()
        try:
            with patch("wet_mcp.token_store.save_token"):
                # Should not raise even without any callback registered.
                await self._run_poll([{"error": "invalid_grant"}])
        finally:
            _reset_callbacks_for_test()

    async def test_post_exception_non_fatal_and_expires(self):
        """Post raising should be caught; deadline expiry exits loop."""
        from wet_mcp.credential_state import _gdrive_token_poll

        class _FailingClient:
            def __init__(self, *a, **kw):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def post(self, *a, **kw):
                raise ConnectionError("boom")

        async def fake_sleep(_):
            return None

        with (
            patch("httpx.AsyncClient", _FailingClient),
            patch("asyncio.sleep", new=fake_sleep),
            patch("wet_mcp.token_store.save_token") as mock_save,
        ):
            # expires_in=0 ensures deadline already passed on next iteration
            await _gdrive_token_poll("cid", "csec", "dev", 0, 0)
            mock_save.assert_not_called()

    async def test_authorization_pending_explicit(self):
        # Cover line 431
        with patch("wet_mcp.token_store.save_token") as mock_save:
            await self._run_poll(
                [
                    {"error": "authorization_pending"},
                    {"access_token": "ok"},
                ]
            )
            mock_save.assert_called_once()

    async def test_internal_exception_explicit(self):
        # Cover line 437-438

        from wet_mcp.credential_state import _gdrive_token_poll

        # Trigger Exception in the loop by making post fail
        responses = [
            "boom",  # Will trigger exception
            {"access_token": "ok"},
        ]
        it = iter(responses)

        class _FakeClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                pass

            async def post(self, *a, **kw):
                val = next(it)
                if val == "boom":
                    raise RuntimeError("boom")
                # Need to return something with .json()
                mock_resp = MagicMock()
                mock_resp.json.return_value = val
                return mock_resp

        async def fake_sleep(_):
            pass

        t_state = [100.0]

        def mock_t():
            val = t_state[0]
            t_state[0] += 1.0
            return val

        with (
            patch("httpx.AsyncClient", return_value=_FakeClient()),
            patch("asyncio.sleep", new=fake_sleep),
            patch("wet_mcp.token_store.save_token") as mock_save,
            patch("time.time", side_effect=mock_t),
        ):
            await _gdrive_token_poll("cid", "csec", "dev", 1, 1000)
            mock_save.assert_called_once()
