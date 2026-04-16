"""Tests for wet_mcp.credential_state -- non-blocking credential state machine."""

import asyncio
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from wet_mcp.credential_state import (
    CLOUD_KEYS,
    SERVER_NAME,
    CredentialState,
    _poll_relay_background,
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
    """Tests for trigger_relay_setup."""

    async def test_skips_when_configured(self):
        """Does not trigger when already CONFIGURED."""
        set_state(CredentialState.CONFIGURED)
        result = await trigger_relay_setup()
        assert result is None  # No URL since not setup_url was set

    async def test_skips_when_local(self):
        """Does not trigger when LOCAL."""
        set_state(CredentialState.LOCAL)
        result = await trigger_relay_setup()
        assert result is None

    async def test_force_overrides_configured(self):
        """force=True triggers even when CONFIGURED."""
        set_state(CredentialState.CONFIGURED)
        mock_session = MagicMock(
            session_id="test-id",
            relay_url="https://relay.example.com/setup/abc",
        )
        with (
            patch(
                "mcp_core.acquire_session_lock",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "mcp_core.relay.client.create_session",
                new_callable=AsyncMock,
                return_value=mock_session,
            ),
            patch(
                "mcp_core.write_session_lock",
                new_callable=AsyncMock,
            ),
            patch(
                "mcp_core.try_open_browser",
                return_value=True,
            ),
        ):
            result = await trigger_relay_setup(force=True)
            assert result == "https://relay.example.com/setup/abc"
            assert get_state() == CredentialState.SETUP_IN_PROGRESS
            # Wait for background task to start (then it will fail since poll is not mocked)
            await asyncio.sleep(0.05)

    async def test_reuses_existing_session_lock(self):
        """Reuses existing session lock if found."""
        from mcp_core import SessionInfo

        existing = SessionInfo(
            session_id="existing-id",
            relay_url="https://relay.example.com/setup/existing",
            created_at=1000.0,
        )
        with patch(
            "mcp_core.acquire_session_lock",
            new_callable=AsyncMock,
            return_value=existing,
        ):
            result = await trigger_relay_setup()
            assert result == "https://relay.example.com/setup/existing"
            assert get_setup_url() == "https://relay.example.com/setup/existing"

    async def test_creates_new_session(self):
        """Creates new session when no lock exists."""
        mock_session = MagicMock(
            session_id="new-id",
            relay_url="https://relay.example.com/setup/new",
        )
        with (
            patch(
                "mcp_core.acquire_session_lock",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "mcp_core.relay.client.create_session",
                new_callable=AsyncMock,
                return_value=mock_session,
            ),
            patch(
                "mcp_core.write_session_lock",
                new_callable=AsyncMock,
            ) as mock_write_lock,
            patch(
                "mcp_core.try_open_browser",
                return_value=True,
            ) as mock_browser,
        ):
            result = await trigger_relay_setup()
            assert result == "https://relay.example.com/setup/new"
            mock_write_lock.assert_awaited_once()
            mock_browser.assert_called_once_with("https://relay.example.com/setup/new")
            # Wait for background task
            await asyncio.sleep(0.05)

    async def test_exception_returns_none(self):
        """On exception, returns None and resets to AWAITING_SETUP."""
        with patch(
            "mcp_core.acquire_session_lock",
            new_callable=AsyncMock,
            side_effect=ConnectionError("unreachable"),
        ):
            result = await trigger_relay_setup()
            assert result is None
            assert get_state() == CredentialState.AWAITING_SETUP


class TestPollRelayBackground:
    """Tests for _poll_relay_background."""

    async def test_success_applies_config(self, monkeypatch):
        """Successful poll applies config and sets CONFIGURED."""
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        mock_session = MagicMock()
        config = {"GEMINI_API_KEY": "from-relay"}

        with (
            patch(
                "mcp_core.relay.client.poll_for_result",
                new_callable=AsyncMock,
                return_value=config,
            ),
            patch("mcp_core.storage.config_file.write_config"),
            patch("wet_mcp.config.settings") as mock_settings,
            patch(
                "mcp_core.release_session_lock",
                new_callable=AsyncMock,
            ),
            patch(
                "wet_mcp.sync.setup_google_auth",
                new_callable=AsyncMock,
                return_value=True,
            ),
            patch(
                "mcp_core.relay.client.send_message",
                new_callable=AsyncMock,
            ),
        ):
            mock_settings.setup_providers = MagicMock()
            await _poll_relay_background(
                "https://relay.example.com", mock_session, 10.0
            )
            assert get_state() == CredentialState.CONFIGURED
            assert os.environ.get("GEMINI_API_KEY") == "from-relay"
            mock_settings.setup_providers.assert_called_once()
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    async def test_relay_skipped_sets_local(self):
        """RELAY_SKIPPED sets state to LOCAL."""
        mock_session = MagicMock()

        with (
            patch(
                "mcp_core.relay.client.poll_for_result",
                new_callable=AsyncMock,
                side_effect=RuntimeError("RELAY_SKIPPED"),
            ),
            patch("mcp_core.set_local_mode") as mock_set_local,
        ):
            await _poll_relay_background(
                "https://relay.example.com", mock_session, 10.0
            )
            assert get_state() == CredentialState.LOCAL
            mock_set_local.assert_called_once_with(SERVER_NAME)

    async def test_relay_skipped_local_mode_error(self):
        """RELAY_SKIPPED with set_local_mode error still sets LOCAL."""
        mock_session = MagicMock()

        with (
            patch(
                "mcp_core.relay.client.poll_for_result",
                new_callable=AsyncMock,
                side_effect=RuntimeError("RELAY_SKIPPED"),
            ),
            patch(
                "mcp_core.set_local_mode",
                side_effect=Exception("file error"),
            ),
        ):
            await _poll_relay_background(
                "https://relay.example.com", mock_session, 10.0
            )
            assert get_state() == CredentialState.LOCAL

    async def test_runtime_error_non_skip(self):
        """Non-RELAY_SKIPPED RuntimeError resets to AWAITING_SETUP."""
        mock_session = MagicMock()
        set_state(CredentialState.SETUP_IN_PROGRESS)

        with patch(
            "mcp_core.relay.client.poll_for_result",
            new_callable=AsyncMock,
            side_effect=RuntimeError("timed out"),
        ):
            await _poll_relay_background(
                "https://relay.example.com", mock_session, 10.0
            )
            assert get_state() == CredentialState.AWAITING_SETUP

    async def test_generic_exception_resets(self):
        """Generic exception resets to AWAITING_SETUP."""
        mock_session = MagicMock()
        set_state(CredentialState.SETUP_IN_PROGRESS)

        with patch(
            "mcp_core.relay.client.poll_for_result",
            new_callable=AsyncMock,
            side_effect=Exception("connection refused"),
        ):
            await _poll_relay_background(
                "https://relay.example.com", mock_session, 10.0
            )
            assert get_state() == CredentialState.AWAITING_SETUP

    async def test_timeout_none_uses_default(self, monkeypatch):
        """When timeout is None, uses 300s default."""
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        mock_session = MagicMock()
        config = {"GEMINI_API_KEY": "test"}

        with (
            patch(
                "mcp_core.relay.client.poll_for_result",
                new_callable=AsyncMock,
                return_value=config,
            ) as mock_poll,
            patch("mcp_core.storage.config_file.write_config"),
            patch("wet_mcp.config.settings") as mock_settings,
            patch("mcp_core.release_session_lock", new_callable=AsyncMock),
            patch(
                "wet_mcp.sync.setup_google_auth",
                new_callable=AsyncMock,
                return_value=True,
            ),
            patch("mcp_core.relay.client.send_message", new_callable=AsyncMock),
        ):
            mock_settings.setup_providers = MagicMock()
            await _poll_relay_background(
                "https://relay.example.com", mock_session, None
            )
            mock_poll.assert_awaited_once_with(
                "https://relay.example.com", mock_session, timeout_s=300.0
            )
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    async def test_does_not_override_existing_env(self, monkeypatch):
        """Config does not override existing env vars."""
        monkeypatch.setenv("GEMINI_API_KEY", "original")
        mock_session = MagicMock()
        config = {"GEMINI_API_KEY": "from-relay"}

        with (
            patch(
                "mcp_core.relay.client.poll_for_result",
                new_callable=AsyncMock,
                return_value=config,
            ),
            patch("mcp_core.storage.config_file.write_config"),
            patch("wet_mcp.config.settings") as mock_settings,
            patch("mcp_core.release_session_lock", new_callable=AsyncMock),
            patch(
                "wet_mcp.sync.setup_google_auth",
                new_callable=AsyncMock,
                return_value=True,
            ),
            patch("mcp_core.relay.client.send_message", new_callable=AsyncMock),
        ):
            mock_settings.setup_providers = MagicMock()
            await _poll_relay_background(
                "https://relay.example.com", mock_session, 10.0
            )
            assert os.environ["GEMINI_API_KEY"] == "original"


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
    """Tests for new setup tool actions (status, start, skip, reset)."""

    async def test_status_action(self, monkeypatch):
        """status action returns current state."""
        import json

        from wet_mcp.server import setup

        set_state(CredentialState.CONFIGURED)
        monkeypatch.setenv("GEMINI_API_KEY", "test")
        result = await setup(action="status")
        data = json.loads(result)
        assert data["state"] == "configured"
        assert "GEMINI_API_KEY" in data["cloud_keys_in_env"]

    async def test_start_action_when_configured(self):
        """start action returns error when CONFIGURED and no force (relay skips)."""
        import json

        from wet_mcp.server import setup

        set_state(CredentialState.CONFIGURED)
        result = await setup(action="start")
        data = json.loads(result)
        assert data["status"] == "error"

    async def test_start_action_force(self):
        """start action with force triggers relay."""
        import json

        from wet_mcp.server import setup

        set_state(CredentialState.CONFIGURED)
        with patch(
            "wet_mcp.credential_state.trigger_relay_setup",
            new_callable=AsyncMock,
            return_value="https://relay.example.com/setup/abc",
        ):
            result = await setup(action="start", force=True)
            data = json.loads(result)
            assert data["status"] == "relay_started"
            assert data["setup_url"] == "https://relay.example.com/setup/abc"

    async def test_start_action_failure(self):
        """start action returns error when relay fails."""
        import json

        from wet_mcp.server import setup

        set_state(CredentialState.AWAITING_SETUP)
        with patch(
            "wet_mcp.credential_state.trigger_relay_setup",
            new_callable=AsyncMock,
            return_value=None,
        ):
            result = await setup(action="start")
            data = json.loads(result)
            assert data["status"] == "error"

    async def test_skip_action(self):
        """skip action sets LOCAL mode."""
        import json

        from wet_mcp.server import setup

        with patch("mcp_core.set_local_mode") as mock_set:
            result = await setup(action="skip")
            data = json.loads(result)
            assert data["status"] == "ok"
            assert get_state() == CredentialState.LOCAL
            mock_set.assert_called_once_with("wet-mcp")

    async def test_reset_action(self):
        """reset action clears state."""
        import json

        from wet_mcp.server import setup

        set_state(CredentialState.CONFIGURED)
        with (
            patch("mcp_core.clear_mode"),
            patch("mcp_core.storage.config_file.delete_config"),
        ):
            result = await setup(action="reset")
            data = json.loads(result)
            assert data["status"] == "ok"
            assert get_state() == CredentialState.AWAITING_SETUP

    async def test_invalid_action_suggests(self):
        """Invalid action includes fuzzy match suggestion."""
        import json

        from wet_mcp.server import setup

        result = await setup(action="statu")
        data = json.loads(result)
        assert "error" in data
        assert "status" in data["error"]  # fuzzy match suggestion

    async def test_complete_action_refreshes_state(self, monkeypatch):
        """complete action re-resolves credentials and transitions to CONFIGURED."""
        import json

        from wet_mcp.server import setup

        set_state(CredentialState.AWAITING_SETUP)
        monkeypatch.setenv("GEMINI_API_KEY", "test-complete-key")
        with patch("wet_mcp.server.settings") as mock_settings:
            mock_settings.setup_providers = MagicMock()
            result = await setup(action="complete")
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


class TestPollRelayBackgroundGDriveAndMessage:
    """Tests for Google Drive OAuth and send_message in _poll_relay_background."""

    async def test_gdrive_oauth_attempted(self, monkeypatch):
        """Google Drive OAuth is attempted when session_id exists."""
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        mock_session = MagicMock(session_id="sess-123")
        config = {"GEMINI_API_KEY": "from-relay"}

        with (
            patch(
                "mcp_core.relay.client.poll_for_result",
                new_callable=AsyncMock,
                return_value=config,
            ),
            patch("mcp_core.storage.config_file.write_config"),
            patch("wet_mcp.config.settings") as mock_settings,
            patch("mcp_core.release_session_lock", new_callable=AsyncMock),
            patch(
                "wet_mcp.sync.setup_google_auth",
                new_callable=AsyncMock,
                return_value=True,
            ) as mock_gdrive,
            patch(
                "mcp_core.relay.client.send_message",
                new_callable=AsyncMock,
            ) as mock_send,
        ):
            mock_settings.setup_providers = MagicMock()
            await _poll_relay_background(
                "https://relay.example.com", mock_session, 10.0
            )
            mock_gdrive.assert_awaited_once_with(
                relay_url="https://relay.example.com", session_id="sess-123"
            )
            mock_send.assert_awaited_once()
            assert get_state() == CredentialState.CONFIGURED
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    async def test_gdrive_oauth_failure_nonfatal(self, monkeypatch):
        """Google Drive OAuth failure is non-fatal."""
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        mock_session = MagicMock(session_id="sess-456")
        config = {"GEMINI_API_KEY": "from-relay"}

        with (
            patch(
                "mcp_core.relay.client.poll_for_result",
                new_callable=AsyncMock,
                return_value=config,
            ),
            patch("mcp_core.storage.config_file.write_config"),
            patch("wet_mcp.config.settings") as mock_settings,
            patch("mcp_core.release_session_lock", new_callable=AsyncMock),
            patch(
                "wet_mcp.sync.setup_google_auth",
                new_callable=AsyncMock,
                side_effect=Exception("OAuth failed"),
            ),
            patch(
                "mcp_core.relay.client.send_message",
                new_callable=AsyncMock,
            ),
        ):
            mock_settings.setup_providers = MagicMock()
            await _poll_relay_background(
                "https://relay.example.com", mock_session, 10.0
            )
            # Still CONFIGURED despite GDrive failure
            assert get_state() == CredentialState.CONFIGURED
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    async def test_send_message_failure_nonfatal(self, monkeypatch):
        """send_message failure is non-fatal (lines 225-226)."""
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        mock_session = MagicMock(session_id="sess-789")
        config = {"GEMINI_API_KEY": "from-relay"}

        with (
            patch(
                "mcp_core.relay.client.poll_for_result",
                new_callable=AsyncMock,
                return_value=config,
            ),
            patch("mcp_core.storage.config_file.write_config"),
            patch("wet_mcp.config.settings") as mock_settings,
            patch("mcp_core.release_session_lock", new_callable=AsyncMock),
            patch(
                "wet_mcp.sync.setup_google_auth",
                new_callable=AsyncMock,
                return_value=True,
            ),
            patch(
                "mcp_core.relay.client.send_message",
                new_callable=AsyncMock,
                side_effect=Exception("network error"),
            ),
        ):
            mock_settings.setup_providers = MagicMock()
            await _poll_relay_background(
                "https://relay.example.com", mock_session, 10.0
            )
            assert get_state() == CredentialState.CONFIGURED
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    async def test_no_session_id_skips_gdrive_and_message(self, monkeypatch):
        """When session has no session_id, skip GDrive OAuth and send_message."""
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        mock_session = MagicMock(spec=[])  # No session_id attribute
        config = {"GEMINI_API_KEY": "from-relay"}

        with (
            patch(
                "mcp_core.relay.client.poll_for_result",
                new_callable=AsyncMock,
                return_value=config,
            ),
            patch("mcp_core.storage.config_file.write_config"),
            patch("wet_mcp.config.settings") as mock_settings,
            patch("mcp_core.release_session_lock", new_callable=AsyncMock),
        ):
            mock_settings.setup_providers = MagicMock()
            await _poll_relay_background(
                "https://relay.example.com", mock_session, 10.0
            )
            assert get_state() == CredentialState.CONFIGURED
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)


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
        """set_gdrive_complete_callback stores the callback."""
        import wet_mcp.credential_state as mod
        from wet_mcp.credential_state import set_gdrive_complete_callback

        def cb():
            pass

        set_gdrive_complete_callback(cb)
        assert mod._on_gdrive_complete is cb
        # cleanup
        mod._on_gdrive_complete = None


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

        cb_called = []
        mod._on_gdrive_complete = lambda: cb_called.append(True)
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

        def bad_cb():
            raise RuntimeError("cb died")

        mod._on_gdrive_complete = bad_cb
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
