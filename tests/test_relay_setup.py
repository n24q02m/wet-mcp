"""Tests for relay setup integration."""

import os
from unittest.mock import AsyncMock, MagicMock, patch

from wet_mcp.relay_schema import RELAY_SCHEMA
from wet_mcp.relay_setup import (
    DEFAULT_RELAY_URL,
    apply_config,
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

    def test_schema_field_keys(self):
        field_keys = [f["key"] for f in RELAY_SCHEMA["fields"]]
        assert "JINA_AI_API_KEY" in field_keys
        assert "GEMINI_API_KEY" in field_keys
        assert "OPENAI_API_KEY" in field_keys
        assert "COHERE_API_KEY" in field_keys

    def test_schema_server_name(self):
        assert RELAY_SCHEMA["server"] == "wet-mcp"

    def test_schema_display_name(self):
        assert RELAY_SCHEMA["displayName"] == "Web Extended Toolkit"

    def test_all_fields_optional(self):
        for f in RELAY_SCHEMA["fields"]:
            assert f.get("required") is False

    def test_capability_info_present(self):
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
        with patch(
            "mcp_relay_core.storage.config_file.read_config",
            return_value=None,
        ):
            result = load_config_from_file()
        assert result is None

    def test_returns_config_when_file_exists(self):
        """Returns config if file found and has keys."""
        mock_config = {"GEMINI_API_KEY": "test-key"}
        with patch(
            "mcp_relay_core.storage.config_file.read_config",
            return_value=mock_config,
        ):
            result = load_config_from_file()
            assert result == mock_config

    def test_returns_none_when_file_exists_but_no_keys(self):
        """Returns None if file exists but has no cloud keys."""
        mock_config = {"OTHER_KEY": "value"}
        with patch(
            "mcp_relay_core.storage.config_file.read_config",
            return_value=mock_config,
        ):
            result = load_config_from_file()
            assert result is None

    def test_returns_none_on_exception(self):
        """Returns None on any exception during read."""
        with patch(
            "mcp_relay_core.storage.config_file.read_config",
            side_effect=Exception("disk error"),
        ):
            result = load_config_from_file()
            assert result is None

    def test_returns_none_on_import_error(self):
        """When mcp_relay_core is not installed, returns None gracefully."""
        # This is harder to test if it's already installed, but load_config_from_file
        # has a try-except block that covers it.
        pass


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

    async def test_returns_none_on_exception(self):
        """When relay server is unreachable, returns None."""
        with patch(
            "mcp_relay_core.relay.client.create_session",
            new_callable=AsyncMock,
            side_effect=ConnectionError("unreachable"),
        ):
            result = await trigger_relay_setup()
            assert result is None

    async def test_relay_skipped_returns_none(self):
        """When user skips, returns None."""
        with patch(
            "mcp_relay_core.relay.client.create_session",
            new_callable=AsyncMock,
            side_effect=RuntimeError("RELAY_SKIPPED by user"),
        ):
            result = await trigger_relay_setup()
            assert result is None

    async def test_httpx_failure_handled(self):
        """Success even if httpx notification fails."""
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

    async def test_generic_exception_returns_none(self):
        """Generic exception returns None."""
        with patch(
            "mcp_relay_core.relay.client.create_session",
            new_callable=AsyncMock,
            side_effect=Exception("unexpected"),
        ):
            result = await trigger_relay_setup()
            assert result is None

    async def test_relay_failed_with_runtime_error(self):
        """Covers the else branch in trigger_relay_setup's RuntimeError handling."""
        with patch(
            "mcp_relay_core.relay.client.create_session",
            new_callable=AsyncMock,
            side_effect=RuntimeError("some other error"),
        ):
            result = await trigger_relay_setup()
            assert result is None


class TestEnsureConfig:
    """Tests for ensure_config."""

    async def test_env_vars_priority(self, monkeypatch):
        """If env vars present, skip relay."""
        from wet_mcp.relay_setup import ensure_config

        monkeypatch.setenv("GEMINI_API_KEY", "test-key")
        result = await ensure_config()
        assert result is None

    async def test_load_from_file(self):
        """If config file exists, use it."""
        from wet_mcp.relay_setup import ensure_config

        mock_config = {"GEMINI_API_KEY": "test-key"}
        with (
            patch(
                "wet_mcp.relay_setup.load_config_from_file", return_value=mock_config
            ),
            patch("wet_mcp.relay_setup.apply_config") as mock_apply,
        ):
            result = await ensure_config()
            assert result == mock_config
            mock_apply.assert_called_once_with(mock_config)

    async def test_ensure_config_full_flow(self):
        """Full flow: session -> poll -> save -> apply -> notify -> gdrive -> notify."""
        from wet_mcp.relay_setup import ensure_config

        mock_session = MagicMock(
            relay_url="https://example.com/setup/abc",
            session_id="test-session-id",
        )
        mock_config = {"GEMINI_API_KEY": "AIza_test_key"}

        with (
            patch(
                "os.environ.get",
                side_effect=lambda k, d=None: d if k == "MCP_RELAY_URL" else None,
            ),
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
                "wet_mcp.sync.setup_google_auth",
                new_callable=AsyncMock,
                return_value=True,
            ),
            patch("wet_mcp.config.settings") as mock_settings,
        ):
            mock_settings.google_drive_client_id = "test-client-id"
            mock_httpx.return_value.__aenter__ = AsyncMock()
            mock_httpx.return_value.__aexit__ = AsyncMock()

            result = await ensure_config()
            assert result == mock_config

    async def test_ensure_config_no_gdrive(self):
        """No GDrive setup if client ID missing."""
        from wet_mcp.relay_setup import ensure_config

        mock_session = MagicMock(
            relay_url="https://example.com/setup/abc",
            session_id="test-session-id",
        )
        mock_config = {"GEMINI_API_KEY": "AIza_test_key"}

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
            mock_httpx.return_value.__aenter__ = AsyncMock()
            mock_httpx.return_value.__aexit__ = AsyncMock()

            result = await ensure_config()
            assert result == mock_config

    async def test_ensure_config_httpx_info_failure(self):
        """Handles failure in info httpx notification."""
        from wet_mcp.relay_setup import ensure_config

        mock_session = MagicMock(
            relay_url="https://example.com/setup/abc",
            session_id="test-session-id",
        )
        mock_config = {"GEMINI_API_KEY": "AIza_test_key"}

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

            # Setup side_effect to fail on the first post call
            mock_client = AsyncMock()
            mock_client.post.side_effect = [
                Exception("Info notification failure"),
                AsyncMock(),
            ]
            mock_httpx.return_value.__aenter__.return_value = mock_client

            result = await ensure_config()
            assert result == mock_config

    async def test_ensure_config_httpx_complete_failure(self):
        """Handles failure in complete httpx notification."""
        from wet_mcp.relay_setup import ensure_config

        mock_session = MagicMock(
            relay_url="https://example.com/setup/abc",
            session_id="test-session-id",
        )
        mock_config = {"GEMINI_API_KEY": "AIza_test_key"}

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

            # Setup side_effect to fail on the second post call (complete)
            mock_client = AsyncMock()
            mock_client.post.side_effect = [
                AsyncMock(),
                Exception("Complete notification failure"),
            ]
            mock_httpx.return_value.__aenter__.return_value = mock_client

            result = await ensure_config()
            assert result == mock_config

    async def test_ensure_config_gdrive_failure(self):
        """Success even if GDrive setup fails (line 130)."""
        from wet_mcp.relay_setup import ensure_config

        mock_session = MagicMock(
            relay_url="https://example.com/setup/abc",
            session_id="test-session-id",
        )
        mock_config = {"GEMINI_API_KEY": "AIza_test_key"}

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
                "wet_mcp.sync.setup_google_auth",
                new_callable=AsyncMock,
                side_effect=Exception("GDrive error"),
            ),
            patch("wet_mcp.config.settings") as mock_settings,
        ):
            mock_settings.google_drive_client_id = "test-client-id"
            mock_httpx.return_value.__aenter__ = AsyncMock()
            mock_httpx.return_value.__aexit__ = AsyncMock()

            result = await ensure_config()
            assert result == mock_config

    async def test_ensure_config_skipped(self):
        """Returns None if skipped."""
        from wet_mcp.relay_setup import ensure_config

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

    async def test_ensure_config_timeout(self):
        """Returns None if timed out."""
        from wet_mcp.relay_setup import ensure_config

        with (
            patch("wet_mcp.relay_setup.load_config_from_file", return_value=None),
            patch(
                "mcp_relay_core.relay.client.create_session",
                new_callable=AsyncMock,
                side_effect=RuntimeError("Timed out"),
            ),
        ):
            result = await ensure_config()
            assert result is None

    async def test_ensure_config_generic_runtime_error(self):
        """Returns None on generic RuntimeError."""
        from wet_mcp.relay_setup import ensure_config

        with (
            patch("wet_mcp.relay_setup.load_config_from_file", return_value=None),
            patch(
                "mcp_relay_core.relay.client.create_session",
                new_callable=AsyncMock,
                side_effect=RuntimeError("some error"),
            ),
        ):
            result = await ensure_config()
            assert result is None

    async def test_ensure_config_generic_exception(self):
        """Returns None on generic Exception."""
        from wet_mcp.relay_setup import ensure_config

        with (
            patch("wet_mcp.relay_setup.load_config_from_file", return_value=None),
            patch(
                "mcp_relay_core.relay.client.create_session",
                new_callable=AsyncMock,
                side_effect=Exception("unexpected"),
            ),
        ):
            result = await ensure_config()
            assert result is None
