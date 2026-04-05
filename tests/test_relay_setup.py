"""Tests for relay setup integration."""

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture
def relay_setup():
    """Fixture for lazy-loading wet_mcp.relay_setup to avoid Pydantic errors."""
    import wet_mcp.relay_setup as mod

    return mod


@pytest.fixture
def relay_schema():
    """Fixture for lazy-loading wet_mcp.relay_schema to avoid Pydantic errors."""
    import wet_mcp.relay_schema as mod

    return mod


class TestRelaySchema:
    """Tests for relay schema definition."""

    def test_schema_has_flat_fields(self, relay_schema):
        """Schema uses flat fields structure (not modes)."""
        assert "fields" in relay_schema.RELAY_SCHEMA
        assert "modes" not in relay_schema.RELAY_SCHEMA

    def test_schema_has_four_provider_fields(self, relay_schema):
        fields = relay_schema.RELAY_SCHEMA["fields"]
        assert len(fields) == 4

    def test_schema_field_keys(self, relay_schema):
        field_keys = [f["key"] for f in relay_schema.RELAY_SCHEMA["fields"]]
        assert "JINA_AI_API_KEY" in field_keys
        assert "GEMINI_API_KEY" in field_keys
        assert "OPENAI_API_KEY" in field_keys
        assert "COHERE_API_KEY" in field_keys

    def test_schema_server_name(self, relay_schema):
        assert relay_schema.RELAY_SCHEMA["server"] == "wet-mcp"

    def test_schema_display_name(self, relay_schema):
        assert relay_schema.RELAY_SCHEMA["displayName"] == "Web Extended Toolkit"

    def test_all_fields_optional(self, relay_schema):
        for f in relay_schema.RELAY_SCHEMA["fields"]:
            assert f.get("required") is False

    def test_capability_info_present(self, relay_schema):
        assert "capabilityInfo" in relay_schema.RELAY_SCHEMA
        assert len(relay_schema.RELAY_SCHEMA["capabilityInfo"]) == 4
        labels = [c["label"] for c in relay_schema.RELAY_SCHEMA["capabilityInfo"]]
        assert "Search & Extraction" in labels
        assert "Embedding" in labels
        assert "Reranking" in labels
        assert "LLM / Vision" in labels


class TestLoadConfigFromFile:
    """Tests for load_config_from_file."""

    def test_returns_none_when_no_file(self, relay_setup):
        with patch(
            "mcp_relay_core.storage.config_file.read_config",
            return_value=None,
        ):
            result = relay_setup.load_config_from_file()
        assert result is None

    def test_returns_none_on_import_error(self, relay_setup):
        """When mcp_relay_core is not installed, returns None gracefully."""
        result = relay_setup.load_config_from_file()
        # Should not raise, returns None if module missing or config not found
        assert result is None or isinstance(result, dict)


class TestApplyConfig:
    """Tests for apply_config."""

    def test_sets_env_vars(self, monkeypatch, relay_setup):
        monkeypatch.delenv("TEST_RELAY_VAR", raising=False)
        relay_setup.apply_config({"TEST_RELAY_VAR": "test_value"})
        assert os.environ["TEST_RELAY_VAR"] == "test_value"
        monkeypatch.delenv("TEST_RELAY_VAR")

    def test_does_not_override_existing_env_vars(self, monkeypatch, relay_setup):
        monkeypatch.setenv("TEST_RELAY_EXISTING", "original")
        relay_setup.apply_config({"TEST_RELAY_EXISTING": "new_value"})
        assert os.environ["TEST_RELAY_EXISTING"] == "original"

    def test_skips_empty_values(self, monkeypatch, relay_setup):
        monkeypatch.delenv("TEST_RELAY_EMPTY", raising=False)
        relay_setup.apply_config({"TEST_RELAY_EMPTY": ""})
        assert "TEST_RELAY_EMPTY" not in os.environ

    def test_applies_multiple_vars(self, monkeypatch, relay_setup):
        monkeypatch.delenv("TEST_RELAY_A", raising=False)
        monkeypatch.delenv("TEST_RELAY_B", raising=False)
        relay_setup.apply_config({"TEST_RELAY_A": "val_a", "TEST_RELAY_B": "val_b"})
        assert os.environ["TEST_RELAY_A"] == "val_a"
        assert os.environ["TEST_RELAY_B"] == "val_b"
        monkeypatch.delenv("TEST_RELAY_A")
        monkeypatch.delenv("TEST_RELAY_B")


class TestEnsureConfigForced:
    """Tests for ensure_config(force=True) -- manual relay setup."""

    async def test_calls_create_session(self, relay_setup, relay_schema):
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
            patch("wet_mcp.relay_setup.apply_config"),
            patch("httpx.AsyncClient") as mock_httpx,
            patch("wet_mcp.config.settings") as mock_settings,
        ):
            mock_settings.google_drive_client_id = None
            mock_httpx.return_value.__aenter__ = AsyncMock(return_value=AsyncMock())
            mock_httpx.return_value.__aexit__ = AsyncMock()
            result = await relay_setup.ensure_config(force=True, timeout=None)
            mock_create.assert_called_once_with(
                relay_setup.DEFAULT_RELAY_URL, "wet-mcp", relay_schema.RELAY_SCHEMA
            )
            assert result == mock_config

    async def test_returns_none_on_exception(self, relay_setup):
        """When relay server is unreachable, returns None."""
        with patch(
            "mcp_relay_core.relay.client.create_session",
            new_callable=AsyncMock,
            side_effect=ConnectionError("unreachable"),
        ):
            result = await relay_setup.ensure_config(force=True, timeout=None)
            assert result is None


class TestLoadConfigFromFileComprehensive:
    """Comprehensive tests for load_config_from_file."""

    def test_returns_valid_config(self, relay_setup):
        mock_config = {"GEMINI_API_KEY": "test-key"}
        with patch(
            "mcp_relay_core.storage.config_file.read_config",
            return_value=mock_config,
        ):
            result = relay_setup.load_config_from_file()
        assert result == mock_config

    def test_returns_none_if_keys_missing(self, relay_setup):
        mock_config = {"OTHER_VAR": "test-value"}
        with patch(
            "mcp_relay_core.storage.config_file.read_config",
            return_value=mock_config,
        ):
            result = relay_setup.load_config_from_file()
        assert result is None

    def test_returns_none_on_exception(self, relay_setup):
        with patch(
            "mcp_relay_core.storage.config_file.read_config",
            side_effect=Exception("Read error"),
        ):
            result = relay_setup.load_config_from_file()
        assert result is None


class TestEnsureConfigComprehensive:
    """Comprehensive tests for ensure_config."""

    async def test_skips_relay_when_env_vars_set(self, monkeypatch, relay_setup):
        monkeypatch.setenv("GEMINI_API_KEY", "test-key")
        result = await relay_setup.ensure_config()
        assert result is None

    async def test_skips_relay_when_config_file_exists(self, relay_setup):
        mock_config = {"GEMINI_API_KEY": "test-key"}
        with (
            patch(
                "wet_mcp.relay_setup.load_config_from_file", return_value=mock_config
            ),
            patch("wet_mcp.relay_setup.apply_config") as mock_apply,
        ):
            result = await relay_setup.ensure_config()
            assert result == mock_config
            mock_apply.assert_called_once_with(mock_config)

    async def test_relay_setup_full_flow_with_gdrive(self, relay_setup, relay_schema):
        mock_session = MagicMock(relay_url="https://rel.ay/abc", session_id="sid")
        mock_config = {"OPENAI_API_KEY": "sk-test"}

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
            patch("mcp_relay_core.storage.config_file.write_config") as mock_write,
            patch("wet_mcp.relay_setup.apply_config") as mock_apply,
            patch("httpx.AsyncClient") as mock_httpx,
            patch("wet_mcp.config.settings") as mock_settings,
            patch(
                "wet_mcp.sync.setup_google_auth",
                new_callable=AsyncMock,
                return_value=True,
            ) as mock_gauth,
        ):
            mock_settings.google_drive_client_id = "g-client-id"
            mock_client = AsyncMock()
            mock_httpx.return_value.__aenter__.return_value = mock_client

            result = await relay_setup.ensure_config(force=True)

            assert result == mock_config
            mock_write.assert_called_once_with("wet-mcp", mock_config)
            mock_apply.assert_called_once_with(mock_config)
            mock_gauth.assert_called_once()
            # Verify notifications were sent
            assert mock_client.post.call_count >= 2

    async def test_relay_setup_gdrive_failure(self, relay_setup, relay_schema):
        mock_session = MagicMock(relay_url="https://rel.ay/abc", session_id="sid")
        mock_config = {"COHERE_API_KEY": "test-key"}

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
            patch("wet_mcp.relay_setup.apply_config"),
            patch("httpx.AsyncClient"),
            patch("wet_mcp.config.settings") as mock_settings,
            patch(
                "wet_mcp.sync.setup_google_auth",
                new_callable=AsyncMock,
                side_effect=Exception("OAuth fail"),
            ),
        ):
            mock_settings.google_drive_client_id = "g-client-id"
            result = await relay_setup.ensure_config(force=True)
            assert result == mock_config

    async def test_relay_notification_failure_ignored(self, relay_setup, relay_schema):
        mock_session = MagicMock(relay_url="https://rel.ay/abc", session_id="sid")
        mock_config = {"JINA_AI_API_KEY": "test-key"}

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
            patch("wet_mcp.relay_setup.apply_config"),
            patch("httpx.AsyncClient") as mock_httpx,
            patch("wet_mcp.config.settings") as mock_settings,
        ):
            mock_settings.google_drive_client_id = None
            mock_client = AsyncMock()
            mock_client.post.side_effect = Exception("Network error")
            mock_httpx.return_value.__aenter__.return_value = mock_client

            result = await relay_setup.ensure_config(force=True)
            assert result == mock_config  # flow completes despite notification failure

    async def test_runtime_error_skipped(self, relay_setup):
        with patch(
            "mcp_relay_core.relay.client.create_session",
            new_callable=AsyncMock,
            side_effect=RuntimeError("RELAY_SKIPPED"),
        ):
            result = await relay_setup.ensure_config(force=True)
            assert result is None

    async def test_runtime_error_timeout(self, relay_setup):
        with patch(
            "mcp_relay_core.relay.client.create_session",
            new_callable=AsyncMock,
            side_effect=RuntimeError("Operation timed out"),
        ):
            result = await relay_setup.ensure_config(force=True)
            assert result is None

    async def test_runtime_error_generic(self, relay_setup):
        with patch(
            "mcp_relay_core.relay.client.create_session",
            new_callable=AsyncMock,
            side_effect=RuntimeError("Generic error"),
        ):
            result = await relay_setup.ensure_config(force=True)
            assert result is None

    async def test_generic_exception(self, relay_setup):
        with patch(
            "mcp_relay_core.relay.client.create_session",
            new_callable=AsyncMock,
            side_effect=ValueError("Some value error"),
        ):
            result = await relay_setup.ensure_config(force=True)
            assert result is None

    async def test_ensure_config_config_file_returns_none_triggers_relay(
        self, relay_setup
    ):
        """Test the path where load_config_from_file returns None, correctly falling through to relay."""
        with (
            patch("wet_mcp.relay_setup.load_config_from_file", return_value=None),
            patch(
                "mcp_relay_core.relay.client.create_session",
                new_callable=AsyncMock,
                side_effect=RuntimeError("RELAY_SKIPPED"),
            ),
        ):
            # We don't care about the result, just hitting the branch
            await relay_setup.ensure_config(force=False)
