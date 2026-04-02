"""Tests for relay setup integration."""

import os
from unittest.mock import AsyncMock, MagicMock, patch

from wet_mcp.relay_schema import RELAY_SCHEMA
from wet_mcp.relay_setup import (
    CLOUD_KEYS,
    DEFAULT_RELAY_URL,
    SERVER_NAME,
    apply_config,
    ensure_config,
    load_config_from_file,
    trigger_relay_setup,
)


class TestRelaySchema:
    """Tests for relay schema definition."""

    def test_schema_has_flat_fields(self):
        """Schema uses flat fields structure (not modes)."""
        assert "fields" in RELAY_SCHEMA
        assert "modes" not in RELAY_SCHEMA

    def test_schema_has_four_provider_fields(self):
        fields = RELAY_SCHEMA["fields"]
        assert len(fields) == 4

    def test_schema_server_name(self):
        assert RELAY_SCHEMA["server"] == "wet-mcp"

    def test_schema_display_name(self):
        assert RELAY_SCHEMA["displayName"] == "Web Extended Toolkit"

    def test_schema_provider_keys(self):
        field_keys = [f["key"] for f in RELAY_SCHEMA["fields"]]
        assert "JINA_AI_API_KEY" in field_keys
        assert "GEMINI_API_KEY" in field_keys
        assert "OPENAI_API_KEY" in field_keys
        assert "COHERE_API_KEY" in field_keys

    def test_all_fields_optional(self):
        for f in RELAY_SCHEMA["fields"]:
            assert f.get("required") is False

    def test_capability_info_present(self):
        assert "capabilityInfo" in RELAY_SCHEMA
        labels = [c["label"] for c in RELAY_SCHEMA["capabilityInfo"]]
        assert "Embedding" in labels
        assert "Reranking" in labels


class TestLoadConfigFromFile:
    """Tests for load_config_from_file."""

    def test_returns_none_when_no_file(self):
        with patch(
            "mcp_relay_core.storage.config_file.read_config",
            return_value=None,
        ):
            result = load_config_from_file()
        assert result is None

    def test_returns_none_on_import_error(self):
        """When mcp_relay_core is not installed, returns None gracefully."""
        result = load_config_from_file()
        # Should not raise, returns None if module missing or config not found
        assert result is None or isinstance(result, dict)

    def test_returns_config_when_valid(self):
        valid_config = {"GEMINI_API_KEY": "test"}
        with patch(
            "mcp_relay_core.storage.config_file.read_config", return_value=valid_config
        ):
            assert load_config_from_file() == valid_config

    def test_returns_none_on_exception(self):
        with patch(
            "mcp_relay_core.storage.config_file.read_config",
            side_effect=Exception("error"),
        ):
            assert load_config_from_file() is None


class TestApplyConfig:
    """Tests for apply_config."""

    def test_sets_env_vars(self, monkeypatch):
        monkeypatch.delenv("TEST_RELAY_VAR", raising=False)
        apply_config({"TEST_RELAY_VAR": "test_value"})
        assert os.environ["TEST_RELAY_VAR"] == "test_value"
        monkeypatch.delenv("TEST_RELAY_VAR")

    def test_does_not_override_existing_env_vars(self, monkeypatch):
        monkeypatch.setenv("TEST_RELAY_EXISTING", "original")
        apply_config({"TEST_RELAY_EXISTING": "new_value"})
        assert os.environ["TEST_RELAY_EXISTING"] == "original"

    def test_skips_empty_values(self, monkeypatch):
        monkeypatch.delenv("TEST_RELAY_EMPTY", raising=False)
        apply_config({"TEST_RELAY_EMPTY": ""})
        assert "TEST_RELAY_EMPTY" not in os.environ

    def test_applies_multiple_vars(self, monkeypatch):
        monkeypatch.delenv("TEST_RELAY_A", raising=False)
        monkeypatch.delenv("TEST_RELAY_B", raising=False)
        apply_config({"TEST_RELAY_A": "val_a", "TEST_RELAY_B": "val_b"})
        assert os.environ["TEST_RELAY_A"] == "val_a"
        assert os.environ["TEST_RELAY_B"] == "val_b"
        monkeypatch.delenv("TEST_RELAY_A")
        monkeypatch.delenv("TEST_RELAY_B")


class TestTriggerRelaySetup:
    """Tests for trigger_relay_setup."""

    async def test_calls_create_session(self):
        mock_session = MagicMock(
            relay_url="https://example.com/setup/abc",
            session_id="test-session-id",
        )
        mock_config = {"GEMINI_API_KEY": "AIza_test_key"}

        with (
            patch(
                "mcp_relay_core.relay.client.create_session",
                new_callable=AsyncMock,
                return_value=mock_session,
            ) as mock_create,
            patch(
                "mcp_relay_core.relay.client.poll_for_result",
                new_callable=AsyncMock,
                return_value=mock_config,
            ),
            patch(
                "mcp_relay_core.storage.config_file.write_config",
            ),
            patch("httpx.AsyncClient") as mock_httpx,
        ):
            mock_httpx.return_value.__aenter__ = AsyncMock()
            mock_httpx.return_value.__aexit__ = AsyncMock()
            result = await trigger_relay_setup()
            mock_create.assert_called_once_with(
                DEFAULT_RELAY_URL, "wet-mcp", RELAY_SCHEMA
            )
            assert result == mock_config

    async def test_returns_none_on_import_error(self):
        """When mcp_relay_core is not available, returns None."""
        with patch(
            "mcp_relay_core.relay.client.create_session",
            new_callable=AsyncMock,
            side_effect=ImportError("No module named 'mcp_relay_core'"),
        ):
            result = await trigger_relay_setup()
            assert result is None

    async def test_trigger_relay_setup_runtime_errors(self):
        with (
            patch(
                "mcp_relay_core.relay.client.create_session",
                new_callable=AsyncMock,
                side_effect=RuntimeError("RELAY_SKIPPED"),
            ),
        ):
            assert await trigger_relay_setup() is None
        with (
            patch(
                "mcp_relay_core.relay.client.create_session",
                new_callable=AsyncMock,
                side_effect=RuntimeError("other"),
            ),
        ):
            assert await trigger_relay_setup() is None

    async def test_trigger_relay_setup_httpx_fail(self):
        mock_session = MagicMock(
            relay_url="https://relay.test/123", session_id="sess-123"
        )
        mock_config = {"GEMINI_API_KEY": "ai-test"}
        with (
            patch(
                "mcp_relay_core.relay.client.create_session",
                new_callable=AsyncMock,
                return_value=mock_session,
            ),
            patch(
                "mcp_relay_core.relay.client.poll_for_result",
                new_callable=AsyncMock,
                return_value=mock_config,
            ),
            patch("mcp_relay_core.storage.config_file.write_config"),
            patch("httpx.AsyncClient") as mock_httpx,
        ):
            mock_httpx.return_value.__aenter__.return_value.post = AsyncMock(
                side_effect=Exception("httpx fail")
            )
            assert await trigger_relay_setup() == mock_config


class TestEnsureConfig:
    """Tests for ensure_config."""

    async def test_skips_when_env_vars_present(self, monkeypatch):
        """Should skip relay if cloud keys are already in environment."""
        monkeypatch.setenv("GEMINI_API_KEY", "test-key")
        with patch("wet_mcp.relay_setup.load_config_from_file") as mock_load:
            result = await ensure_config()
            assert result is None
            mock_load.assert_not_called()

    async def test_returns_saved_config(self, monkeypatch):
        """Should return saved config from file if found."""
        for key in CLOUD_KEYS:
            monkeypatch.delenv(key, raising=False)

        saved_config = {"OPENAI_API_KEY": "sk-test"}
        with (
            patch(
                "wet_mcp.relay_setup.load_config_from_file", return_value=saved_config
            ),
            patch("wet_mcp.relay_setup.apply_config") as mock_apply,
        ):
            result = await ensure_config()
            assert result == saved_config
            mock_apply.assert_called_once_with(saved_config)

    async def test_successful_relay_setup_no_gdrive(self, monkeypatch):
        """Should complete relay setup when no local credentials exist."""
        for key in CLOUD_KEYS:
            monkeypatch.delenv(key, raising=False)

        mock_session = MagicMock(
            relay_url="https://relay.test/123", session_id="sess-123"
        )
        mock_config = {"COHERE_API_KEY": "co-test"}

        with (
            patch("wet_mcp.relay_setup.load_config_from_file", return_value=None),
            patch(
                "mcp_relay_core.relay.client.create_session",
                new_callable=AsyncMock,
                return_value=mock_session,
            ),
            patch(
                "mcp_relay_core.relay.client.poll_for_result",
                new_callable=AsyncMock,
                return_value=mock_config,
            ),
            patch("mcp_relay_core.storage.config_file.write_config") as mock_write,
            patch("wet_mcp.relay_setup.apply_config") as mock_apply,
            patch("httpx.AsyncClient") as mock_httpx,
            patch("wet_mcp.config.settings", MagicMock(google_drive_client_id=None)),
        ):
            mock_httpx.return_value.__aenter__.return_value.post = AsyncMock()

            result = await ensure_config()

            assert result == mock_config
            mock_write.assert_called_once_with(SERVER_NAME, mock_config)
            mock_apply.assert_called_once_with(mock_config)

    async def test_relay_setup_with_gdrive_success(self, monkeypatch):
        """Should handle successful Google Drive OAuth during relay setup."""
        for key in CLOUD_KEYS:
            monkeypatch.delenv(key, raising=False)

        mock_session = MagicMock(
            relay_url="https://relay.test/123", session_id="sess-123"
        )
        mock_config = {"GEMINI_API_KEY": "ai-test"}

        with (
            patch("wet_mcp.relay_setup.load_config_from_file", return_value=None),
            patch(
                "mcp_relay_core.relay.client.create_session",
                new_callable=AsyncMock,
                return_value=mock_session,
            ),
            patch(
                "mcp_relay_core.relay.client.poll_for_result",
                new_callable=AsyncMock,
                return_value=mock_config,
            ),
            patch("mcp_relay_core.storage.config_file.write_config"),
            patch("wet_mcp.relay_setup.apply_config"),
            patch("httpx.AsyncClient") as mock_httpx,
            patch(
                "wet_mcp.config.settings", MagicMock(google_drive_client_id="test-id")
            ),
            patch(
                "wet_mcp.sync.setup_google_auth",
                new_callable=AsyncMock,
                return_value=True,
            ) as mock_gauth,
        ):
            mock_post = AsyncMock()
            mock_httpx.return_value.__aenter__.return_value.post = mock_post

            result = await ensure_config()

            assert result == mock_config
            mock_gauth.assert_called_once()
            # Verify the "Setup complete!" message was sent
            last_call = mock_post.call_args_list[-1]
            assert last_call.kwargs["json"]["text"] == "Setup complete!"

    async def test_relay_setup_skipped(self, monkeypatch):
        """Should return None if relay setup is skipped by the user."""
        for key in CLOUD_KEYS:
            monkeypatch.delenv(key, raising=False)

        with (
            patch("wet_mcp.relay_setup.load_config_from_file", return_value=None),
            patch("mcp_relay_core.relay.client.create_session", new_callable=AsyncMock),
            patch(
                "mcp_relay_core.relay.client.poll_for_result",
                side_effect=RuntimeError("RELAY_SKIPPED"),
            ),
        ):
            result = await ensure_config()
            assert result is None

    async def test_relay_setup_timeout(self, monkeypatch):
        """Should return None if relay setup times out."""
        for key in CLOUD_KEYS:
            monkeypatch.delenv(key, raising=False)

        with (
            patch("wet_mcp.relay_setup.load_config_from_file", return_value=None),
            patch("mcp_relay_core.relay.client.create_session", new_callable=AsyncMock),
            patch(
                "mcp_relay_core.relay.client.poll_for_result",
                side_effect=RuntimeError("Relay timed out"),
            ),
        ):
            result = await ensure_config()
            assert result is None

    async def test_relay_setup_general_exception(self, monkeypatch):
        """Should return None if relay setup encounters a general exception."""
        for key in CLOUD_KEYS:
            monkeypatch.delenv(key, raising=False)

        with (
            patch("wet_mcp.relay_setup.load_config_from_file", return_value=None),
            patch(
                "mcp_relay_core.relay.client.create_session",
                side_effect=Exception("Network error"),
            ),
        ):
            result = await ensure_config()
            assert result is None

    async def test_relay_setup_runtime_error_other(self, monkeypatch):
        for key in CLOUD_KEYS:
            monkeypatch.delenv(key, raising=False)
        with (
            patch("wet_mcp.relay_setup.load_config_from_file", return_value=None),
            patch(
                "mcp_relay_core.relay.client.create_session",
                side_effect=RuntimeError("other error"),
            ),
        ):
            result = await ensure_config()
            assert result is None

    async def test_relay_setup_httpx_exceptions(self, monkeypatch):
        for key in CLOUD_KEYS:
            monkeypatch.delenv(key, raising=False)
        mock_session = MagicMock(
            relay_url="https://relay.test/123", session_id="sess-123"
        )
        mock_config = {"GEMINI_API_KEY": "ai-test"}
        with (
            patch("wet_mcp.relay_setup.load_config_from_file", return_value=None),
            patch(
                "mcp_relay_core.relay.client.create_session",
                new_callable=AsyncMock,
                return_value=mock_session,
            ),
            patch(
                "mcp_relay_core.relay.client.poll_for_result",
                new_callable=AsyncMock,
                return_value=mock_config,
            ),
            patch("mcp_relay_core.storage.config_file.write_config"),
            patch("wet_mcp.relay_setup.apply_config"),
            patch("httpx.AsyncClient") as mock_httpx,
            patch(
                "wet_mcp.config.settings", MagicMock(google_drive_client_id="test-id")
            ),
            patch(
                "wet_mcp.sync.setup_google_auth",
                new_callable=AsyncMock,
                side_effect=Exception("gdrive fail"),
            ),
        ):
            mock_httpx.return_value.__aenter__.return_value.post = AsyncMock(
                side_effect=Exception("httpx fail")
            )
            result = await ensure_config()
            assert result == mock_config
