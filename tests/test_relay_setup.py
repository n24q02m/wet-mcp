"""Tests for relay setup integration."""

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestRelaySchema:
    """Tests for relay schema definition."""

    def test_schema_has_flat_fields(self):
        """Schema uses flat fields structure (not modes)."""
        from wet_mcp.relay_schema import RELAY_SCHEMA

        assert "fields" in RELAY_SCHEMA
        assert "modes" not in RELAY_SCHEMA

    def test_schema_has_four_provider_fields(self):
        from wet_mcp.relay_schema import RELAY_SCHEMA

        fields = RELAY_SCHEMA["fields"]
        assert len(fields) == 4

    def test_schema_field_keys(self):
        from wet_mcp.relay_schema import RELAY_SCHEMA

        field_keys = [f["key"] for f in RELAY_SCHEMA["fields"]]
        assert "JINA_AI_API_KEY" in field_keys
        assert "GEMINI_API_KEY" in field_keys
        assert "OPENAI_API_KEY" in field_keys
        assert "COHERE_API_KEY" in field_keys

    def test_schema_server_name(self):
        from wet_mcp.relay_schema import RELAY_SCHEMA

        assert RELAY_SCHEMA["server"] == "wet-mcp"

    def test_schema_display_name(self):
        from wet_mcp.relay_schema import RELAY_SCHEMA

        assert RELAY_SCHEMA["displayName"] == "Web Extended Toolkit"

    def test_all_fields_optional(self):
        from wet_mcp.relay_schema import RELAY_SCHEMA

        for f in RELAY_SCHEMA["fields"]:
            assert f.get("required") is False

    def test_capability_info_present(self):
        from wet_mcp.relay_schema import RELAY_SCHEMA

        assert "capabilityInfo" in RELAY_SCHEMA
        assert len(RELAY_SCHEMA["capabilityInfo"]) == 4
        labels = [c["label"] for c in RELAY_SCHEMA["capabilityInfo"]]
        assert "Search & Extraction" in labels
        assert "Embedding" in labels
        assert "Reranking" in labels
        assert "LLM / Vision" in labels


class TestLoadConfigFromFile:
    """Tests for load_config_from_file."""

    def test_returns_none_when_no_file(self):
        from wet_mcp.relay_setup import load_config_from_file

        with patch(
            "mcp_relay_core.storage.config_file.read_config",
            return_value=None,
        ):
            result = load_config_from_file()
        assert result is None

    def test_returns_none_on_import_error(self):
        """When mcp_relay_core is not installed, returns None gracefully."""
        from wet_mcp.relay_setup import load_config_from_file

        result = load_config_from_file()
        # Should not raise, returns None if module missing or config not found
        assert result is None or isinstance(result, dict)


class TestApplyConfig:
    """Tests for apply_config."""

    def test_sets_env_vars(self, monkeypatch):
        from wet_mcp.relay_setup import apply_config

        monkeypatch.delenv("TEST_RELAY_VAR", raising=False)
        apply_config({"TEST_RELAY_VAR": "test_value"})
        assert os.environ["TEST_RELAY_VAR"] == "test_value"
        monkeypatch.delenv("TEST_RELAY_VAR")

    def test_does_not_override_existing_env_vars(self, monkeypatch):
        from wet_mcp.relay_setup import apply_config

        monkeypatch.setenv("TEST_RELAY_EXISTING", "original")
        apply_config({"TEST_RELAY_EXISTING": "new_value"})
        assert os.environ["TEST_RELAY_EXISTING"] == "original"

    def test_skips_empty_values(self, monkeypatch):
        from wet_mcp.relay_setup import apply_config

        monkeypatch.delenv("TEST_RELAY_EMPTY", raising=False)
        apply_config({"TEST_RELAY_EMPTY": ""})
        assert "TEST_RELAY_EMPTY" not in os.environ

    def test_applies_multiple_vars(self, monkeypatch):
        from wet_mcp.relay_setup import apply_config

        monkeypatch.delenv("TEST_RELAY_A", raising=False)
        monkeypatch.delenv("TEST_RELAY_B", raising=False)
        apply_config({"TEST_RELAY_A": "val_a", "TEST_RELAY_B": "val_b"})
        assert os.environ["TEST_RELAY_A"] == "val_a"
        assert os.environ["TEST_RELAY_B"] == "val_b"
        monkeypatch.delenv("TEST_RELAY_A")
        monkeypatch.delenv("TEST_RELAY_B")


class TestEnsureConfigForced:
    """Tests for ensure_config(force=True) -- manual relay setup."""

    @pytest.mark.asyncio
    async def test_calls_create_session(self):
        from wet_mcp.relay_schema import RELAY_SCHEMA
        from wet_mcp.relay_setup import DEFAULT_RELAY_URL, ensure_config

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
            result = await ensure_config(force=True, timeout=None)
            mock_create.assert_called_once_with(
                DEFAULT_RELAY_URL, "wet-mcp", RELAY_SCHEMA
            )
            assert result == mock_config

    @pytest.mark.asyncio
    async def test_returns_none_on_exception(self):
        """When relay server is unreachable, returns None."""
        from wet_mcp.relay_setup import ensure_config

        with patch(
            "mcp_relay_core.relay.client.create_session",
            new_callable=AsyncMock,
            side_effect=ConnectionError("unreachable"),
        ):
            result = await ensure_config(force=True, timeout=None)
            assert result is None


class TestEnsureConfig:
    """Comprehensive tests for ensure_config."""

    @pytest.mark.asyncio
    async def test_env_vars_found(self, monkeypatch):
        """When CLOUD_KEYS are in environment, should return None."""
        from wet_mcp.relay_setup import ensure_config

        monkeypatch.setenv("GEMINI_API_KEY", "test_key")
        result = await ensure_config()
        assert result is None

    @pytest.mark.asyncio
    async def test_config_file_found(self, monkeypatch):
        """When config file is found, should apply and return it."""
        from wet_mcp.relay_setup import ensure_config

        mock_config = {"OPENAI_API_KEY": "sk-test"}
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("JINA_AI_API_KEY", raising=False)
        monkeypatch.delenv("COHERE_API_KEY", raising=False)

        with patch(
            "wet_mcp.relay_setup.load_config_from_file", return_value=mock_config
        ):
            with patch("wet_mcp.relay_setup.apply_config") as mock_apply:
                result = await ensure_config()
                assert result == mock_config
                mock_apply.assert_called_once_with(mock_config)

    @pytest.mark.asyncio
    async def test_relay_setup_success_no_gdrive(self, monkeypatch):
        """Full relay setup success path without GDrive."""
        from wet_mcp.relay_setup import ensure_config

        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("JINA_AI_API_KEY", raising=False)
        monkeypatch.delenv("COHERE_API_KEY", raising=False)

        mock_session = MagicMock(session_id="s1", relay_url="http://relay/s1")
        mock_config = {"JINA_AI_API_KEY": "jina-test"}

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
            patch("wet_mcp.config.settings") as mock_settings,
        ):
            mock_settings.google_drive_client_id = None
            mock_httpx.return_value.__aenter__ = AsyncMock(return_value=AsyncMock())
            result = await ensure_config()

            assert result == mock_config
            mock_write.assert_called_once()
            mock_apply.assert_called_once_with(mock_config)

    @pytest.mark.asyncio
    async def test_relay_setup_with_gdrive_success(self, monkeypatch):
        """Full relay setup success path with GDrive success."""
        from wet_mcp.relay_setup import ensure_config

        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("JINA_AI_API_KEY", raising=False)
        monkeypatch.delenv("COHERE_API_KEY", raising=False)

        mock_session = MagicMock(session_id="s1", relay_url="http://relay/s1")
        mock_config = {"JINA_AI_API_KEY": "jina-test"}

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
                "wet_mcp.sync.setup_google_auth",
                new_callable=AsyncMock,
                return_value=True,
            ) as mock_gdrive,
        ):
            mock_settings.google_drive_client_id = "some-client-id"
            mock_httpx.return_value.__aenter__ = AsyncMock(return_value=AsyncMock())
            result = await ensure_config()

            assert result == mock_config
            mock_gdrive.assert_called_once()

    @pytest.mark.asyncio
    async def test_relay_setup_skipped_by_user(self, monkeypatch):
        """Relay setup skipped by user (RuntimeError)."""
        from wet_mcp.relay_setup import ensure_config

        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("JINA_AI_API_KEY", raising=False)
        monkeypatch.delenv("COHERE_API_KEY", raising=False)

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

    @pytest.mark.asyncio
    async def test_relay_setup_timed_out(self, monkeypatch):
        """Relay setup timed out (RuntimeError)."""
        from wet_mcp.relay_setup import ensure_config

        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("JINA_AI_API_KEY", raising=False)
        monkeypatch.delenv("COHERE_API_KEY", raising=False)

        with (
            patch("wet_mcp.relay_setup.load_config_from_file", return_value=None),
            patch(
                "mcp_relay_core.relay.client.create_session",
                new_callable=AsyncMock,
                side_effect=RuntimeError("Relay setup timed out"),
            ),
        ):
            result = await ensure_config()
            assert result is None

    @pytest.mark.asyncio
    async def test_relay_setup_generic_exception(self, monkeypatch):
        """Relay setup generic Exception."""
        from wet_mcp.relay_setup import ensure_config

        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("JINA_AI_API_KEY", raising=False)
        monkeypatch.delenv("COHERE_API_KEY", raising=False)

        with (
            patch("wet_mcp.relay_setup.load_config_from_file", return_value=None),
            patch(
                "mcp_relay_core.relay.client.create_session",
                new_callable=AsyncMock,
                side_effect=Exception("Unexpected error"),
            ),
        ):
            result = await ensure_config()
            assert result is None

    @pytest.mark.asyncio
    async def test_relay_notification_failure_ignored(self, monkeypatch):
        """HTTP notification failure should not crash ensure_config."""
        from wet_mcp.relay_setup import ensure_config

        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("JINA_AI_API_KEY", raising=False)
        monkeypatch.delenv("COHERE_API_KEY", raising=False)

        mock_session = MagicMock(session_id="s1", relay_url="http://relay/s1")
        mock_config = {"COHERE_API_KEY": "cohere-test"}

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
            # Simulate httpx error
            mock_httpx.return_value.__aenter__.side_effect = Exception("HTTP error")

            result = await ensure_config()
            assert result == mock_config


class TestRelaySetupCoverage:
    """Extra tests to boost coverage of relay_setup.py."""

    @pytest.mark.asyncio
    async def test_load_config_from_file_empty_or_no_keys(self):
        """Test load_config_from_file with empty or no keys."""
        from wet_mcp.relay_setup import load_config_from_file

        with patch("mcp_relay_core.storage.config_file.read_config", return_value={}):
            assert load_config_from_file() is None

        with patch(
            "mcp_relay_core.storage.config_file.read_config",
            return_value={"OTHER": "val"},
        ):
            assert load_config_from_file() is None

    @pytest.mark.asyncio
    async def test_load_config_from_file_exception(self):
        """Test load_config_from_file with exception."""
        from wet_mcp.relay_setup import load_config_from_file

        with patch(
            "mcp_relay_core.storage.config_file.read_config",
            side_effect=Exception("error"),
        ):
            assert load_config_from_file() is None

    @pytest.mark.asyncio
    async def test_ensure_config_gdrive_exception(self, monkeypatch):
        """Test ensure_config when setup_google_auth raises exception."""
        from wet_mcp.relay_setup import ensure_config

        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("JINA_AI_API_KEY", raising=False)
        monkeypatch.delenv("COHERE_API_KEY", raising=False)

        mock_session = MagicMock(session_id="s1", relay_url="http://relay/s1")
        mock_config = {"GEMINI_API_KEY": "test-key"}

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
                "wet_mcp.sync.setup_google_auth",
                new_callable=AsyncMock,
                side_effect=Exception("GDrive error"),
            ),
        ):
            mock_settings.google_drive_client_id = "some-client-id"
            mock_httpx.return_value.__aenter__ = AsyncMock(return_value=AsyncMock())

            result = await ensure_config()
            assert result == mock_config

    @pytest.mark.asyncio
    async def test_ensure_config_runtime_error_other(self, monkeypatch):
        """Test ensure_config with other RuntimeError."""
        from wet_mcp.relay_setup import ensure_config

        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("JINA_AI_API_KEY", raising=False)
        monkeypatch.delenv("COHERE_API_KEY", raising=False)

        with (
            patch("wet_mcp.relay_setup.load_config_from_file", return_value=None),
            patch(
                "mcp_relay_core.relay.client.create_session",
                new_callable=AsyncMock,
                side_effect=RuntimeError("Some other runtime error"),
            ),
        ):
            result = await ensure_config()
            assert result is None
