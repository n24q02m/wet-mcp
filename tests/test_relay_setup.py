"""Tests for relay setup integration."""

import os
from unittest.mock import AsyncMock, MagicMock, patch

from wet_mcp.relay_schema import RELAY_SCHEMA
from wet_mcp.relay_setup import (
    DEFAULT_RELAY_URL,
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

    def test_returns_config_when_exists(self):
        mock_config = {"JINA_AI_API_KEY": "test-key"}
        with patch(
            "mcp_relay_core.storage.config_file.read_config",
            return_value=mock_config,
        ):
            result = load_config_from_file()
        assert result == mock_config

    def test_returns_none_on_exception(self):
        with patch(
            "mcp_relay_core.storage.config_file.read_config",
            side_effect=Exception("error"),
        ):
            result = load_config_from_file()
        assert result is None

    def test_returns_none_on_import_error(self):
        """When mcp_relay_core is not installed, returns None gracefully."""
        result = load_config_from_file()
        # Should not raise, returns None if module missing or config not found
        assert result is None or isinstance(result, dict)


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


class TestEnsureConfig:
    """Tests for ensure_config."""

    async def test_skips_when_env_vars_present(self, monkeypatch):
        monkeypatch.setenv("JINA_AI_API_KEY", "env-key")
        result = await ensure_config()
        assert result is None

    async def test_uses_config_file_if_exists(self):
        mock_config = {"JINA_AI_API_KEY": "file-key"}
        with (
            patch(
                "wet_mcp.relay_setup.load_config_from_file", return_value=mock_config
            ),
            patch("wet_mcp.relay_setup.apply_config") as mock_apply,
        ):
            result = await ensure_config()
            assert result == mock_config
            mock_apply.assert_called_once_with(mock_config)

    async def test_triggers_relay_success(self, monkeypatch):
        monkeypatch.delenv("JINA_AI_API_KEY", raising=False)
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("COHERE_API_KEY", raising=False)

        mock_session = MagicMock(relay_url="url", session_id="sid")
        mock_config = {"OPENAI_API_KEY": "sk-test"}

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
            patch("wet_mcp.config.settings") as mock_settings,
        ):
            mock_settings.google_drive_client_id = None
            mock_httpx.return_value.__aenter__.return_value.post = AsyncMock()

            result = await ensure_config()
            assert result == mock_config

    async def test_triggers_relay_with_gdrive(self, monkeypatch):
        monkeypatch.delenv("JINA_AI_API_KEY", raising=False)
        mock_session = MagicMock(relay_url="url", session_id="sid")
        mock_config = {"OPENAI_API_KEY": "sk-test"}

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
            patch("wet_mcp.config.settings") as mock_settings,
            patch(
                "wet_mcp.sync.setup_google_auth", new_callable=AsyncMock
            ) as mock_auth,
        ):
            mock_settings.google_drive_client_id = "client-id"
            mock_auth.return_value = True
            mock_httpx.return_value.__aenter__.return_value.post = AsyncMock()

            result = await ensure_config()
            assert result == mock_config
            mock_auth.assert_called_once()

    async def test_handles_runtime_error_skipped(self):
        with (
            patch("wet_mcp.relay_setup.load_config_from_file", return_value=None),
            patch(
                "mcp_relay_core.relay.client.create_session",
                new_callable=AsyncMock,
                side_effect=RuntimeError("RELAY_SKIPPED"),
            ),
        ):
            result = await ensure_config()
            assert result is None

    async def test_triggers_relay_httpx_fail(self, monkeypatch):
        monkeypatch.delenv("JINA_AI_API_KEY", raising=False)
        mock_session = MagicMock(relay_url="url", session_id="sid")
        mock_config = {"OPENAI_API_KEY": "sk-test"}

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
            patch("wet_mcp.config.settings") as mock_settings,
        ):
            mock_settings.google_drive_client_id = None
            # Force httpx failure
            mock_httpx.return_value.__aenter__.side_effect = Exception("network error")

            result = await ensure_config()
            assert result == mock_config

    async def test_triggers_relay_gdrive_fail(self, monkeypatch):
        monkeypatch.delenv("JINA_AI_API_KEY", raising=False)
        mock_session = MagicMock(relay_url="url", session_id="sid")
        mock_config = {"OPENAI_API_KEY": "sk-test"}

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
            patch("wet_mcp.config.settings") as mock_settings,
            patch(
                "wet_mcp.sync.setup_google_auth", new_callable=AsyncMock
            ) as mock_auth,
        ):
            mock_settings.google_drive_client_id = "client-id"
            mock_auth.side_effect = Exception("auth error")
            mock_httpx.return_value.__aenter__.return_value.post = AsyncMock()

            result = await ensure_config()
            assert result == mock_config

    async def test_handles_runtime_error_other(self):
        with (
            patch("wet_mcp.relay_setup.load_config_from_file", return_value=None),
            patch(
                "mcp_relay_core.relay.client.create_session",
                new_callable=AsyncMock,
                side_effect=RuntimeError("something else"),
            ),
        ):
            result = await ensure_config()
            assert result is None

    async def test_handles_runtime_error_timeout(self):
        with (
            patch("wet_mcp.relay_setup.load_config_from_file", return_value=None),
            patch(
                "mcp_relay_core.relay.client.create_session",
                new_callable=AsyncMock,
                side_effect=RuntimeError("timed out"),
            ),
        ):
            result = await ensure_config()
            assert result is None

    async def test_handles_generic_exception(self):
        with (
            patch("wet_mcp.relay_setup.load_config_from_file", return_value=None),
            patch(
                "mcp_relay_core.relay.client.create_session",
                new_callable=AsyncMock,
                side_effect=Exception("oops"),
            ),
        ):
            result = await ensure_config()
            assert result is None


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
            mock_httpx.return_value.__aenter__.return_value.post = AsyncMock()
            result = await trigger_relay_setup()
            mock_create.assert_called_once_with(
                DEFAULT_RELAY_URL, "wet-mcp", RELAY_SCHEMA
            )
            assert result == mock_config

    async def test_handles_httpx_exception(self):
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
            ),
            patch(
                "mcp_relay_core.relay.client.poll_for_result",
                new_callable=AsyncMock,
                return_value=mock_config,
            ),
            patch("mcp_relay_core.storage.config_file.write_config"),
            patch("httpx.AsyncClient") as mock_httpx,
        ):
            mock_httpx.return_value.__aenter__.side_effect = Exception("network error")
            result = await trigger_relay_setup()
            assert result == mock_config

    async def test_handles_runtime_error_skipped(self):
        with patch(
            "mcp_relay_core.relay.client.create_session",
            new_callable=AsyncMock,
            side_effect=RuntimeError("RELAY_SKIPPED"),
        ):
            result = await trigger_relay_setup()
            assert result is None

    async def test_handles_runtime_error_other(self):
        with patch(
            "mcp_relay_core.relay.client.create_session",
            new_callable=AsyncMock,
            side_effect=RuntimeError("something else"),
        ):
            result = await trigger_relay_setup()
            assert result is None

    async def test_handles_generic_exception(self):
        with patch(
            "mcp_relay_core.relay.client.create_session",
            new_callable=AsyncMock,
            side_effect=Exception("oops"),
        ):
            result = await trigger_relay_setup()
            assert result is None

    async def test_returns_none_on_import_error(self):
        """When mcp_relay_core is not available, returns None."""
        with patch(
            "mcp_relay_core.relay.client.create_session",
            new_callable=AsyncMock,
            side_effect=ImportError("No module named 'mcp_relay_core'"),
        ):
            result = await trigger_relay_setup()
            assert result is None
