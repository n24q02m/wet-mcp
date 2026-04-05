"""Tests for relay setup integration."""

import importlib.util
import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def load_relay_setup_isolated():
    """Load wet_mcp.relay_setup isolated from other modules that might trigger Pydantic or Numpy issues."""
    module_name = "wet_mcp.relay_setup"
    if module_name in sys.modules:
        return sys.modules[module_name]

    # Path to src/wet_mcp/relay_setup.py
    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    file_path = os.path.join(project_root, "src", "wet_mcp", "relay_setup.py")

    spec = importlib.util.spec_from_file_location(module_name, file_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not load {module_name} from {file_path}")

    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def load_relay_schema_isolated():
    """Load wet_mcp.relay_schema isolated."""
    module_name = "wet_mcp.relay_schema"
    if module_name in sys.modules:
        return sys.modules[module_name]

    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    file_path = os.path.join(project_root, "src", "wet_mcp", "relay_schema.py")

    spec = importlib.util.spec_from_file_location(module_name, file_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not load {module_name} from {file_path}")

    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def relay_setup():
    return load_relay_setup_isolated()


@pytest.fixture
def relay_schema():
    return load_relay_schema_isolated().RELAY_SCHEMA


class TestRelaySchema:
    """Tests for relay schema definition."""

    def test_schema_has_flat_fields(self, relay_schema):
        """Schema uses flat fields structure (not modes)."""
        assert "fields" in relay_schema
        assert "modes" not in relay_schema

    def test_schema_has_four_provider_fields(self, relay_schema):
        fields = relay_schema["fields"]
        assert len(fields) == 4

    def test_schema_field_keys(self, relay_schema):
        field_keys = [f["key"] for f in relay_schema["fields"]]
        assert "JINA_AI_API_KEY" in field_keys
        assert "GEMINI_API_KEY" in field_keys
        assert "OPENAI_API_KEY" in field_keys
        assert "COHERE_API_KEY" in field_keys

    def test_schema_server_name(self, relay_schema):
        assert relay_schema["server"] == "wet-mcp"

    def test_schema_display_name(self, relay_schema):
        assert relay_schema["displayName"] == "Web Extended Toolkit"

    def test_all_fields_optional(self, relay_schema):
        for f in relay_schema["fields"]:
            assert f.get("required") is False

    def test_capability_info_present(self, relay_schema):
        assert "capabilityInfo" in relay_schema
        assert len(relay_schema["capabilityInfo"]) == 4
        labels = [c["label"] for c in relay_schema["capabilityInfo"]]
        assert "Search & Extraction" in labels
        assert "Embedding" in labels
        assert "Reranking" in labels
        assert "LLM / Vision" in labels


class TestLoadConfigFromFile:
    """Tests for load_config_from_file."""

    def test_returns_none_when_no_file(self, relay_setup):
        mock_storage = MagicMock()
        mock_storage.read_config.return_value = None
        with patch.dict(
            "sys.modules", {"mcp_relay_core.storage.config_file": mock_storage}
        ):
            result = relay_setup.load_config_from_file()
        assert result is None

    def test_returns_config_when_file_exists(self, relay_setup):
        mock_storage = MagicMock()
        mock_config = {"GEMINI_API_KEY": "test_key"}
        mock_storage.read_config.return_value = mock_config
        with patch.dict(
            "sys.modules", {"mcp_relay_core.storage.config_file": mock_storage}
        ):
            result = relay_setup.load_config_from_file()
        assert result == mock_config

    def test_returns_none_when_file_exists_but_no_keys(self, relay_setup):
        mock_storage = MagicMock()
        mock_config = {"OTHER_KEY": "test_key"}
        mock_storage.read_config.return_value = mock_config
        with patch.dict(
            "sys.modules", {"mcp_relay_core.storage.config_file": mock_storage}
        ):
            result = relay_setup.load_config_from_file()
        assert result is None

    def test_returns_none_on_import_error(self, relay_setup):
        """When mcp_relay_core is not installed, returns None gracefully."""
        # Using a non-existent module name to trigger ImportError inside the function
        with patch.dict(
            "sys.modules", {"mcp_relay_core.storage.config_file": MagicMock()}
        ):
            # This is tricky because the module is already in sys.modules from the mock
            # Let's delete it instead
            del sys.modules["mcp_relay_core.storage.config_file"]
            # And make sure it can't be re-imported
            with patch.dict(
                "sys.modules", {"mcp_relay_core.storage.config_file": None}
            ):
                result = relay_setup.load_config_from_file()
        assert result is None


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

    def test_apply_config_logging(self, caplog, monkeypatch, relay_setup):
        monkeypatch.delenv("TEST_LOG_VAR", raising=False)
        from loguru import logger

        handler_id = logger.add(caplog.handler, format="{message}", level="DEBUG")
        try:
            relay_setup.apply_config({"TEST_LOG_VAR": "log_val"})
            assert os.environ["TEST_LOG_VAR"] == "log_val"
            assert "Applied relay config: TEST_LOG_VAR" in caplog.text
        finally:
            logger.remove(handler_id)
            monkeypatch.delenv("TEST_LOG_VAR")

    def test_apply_config_falsy_logging(self, caplog, monkeypatch, relay_setup):
        monkeypatch.delenv("TEST_FALSY_VAR", raising=False)
        from loguru import logger

        handler_id = logger.add(caplog.handler, format="{message}", level="DEBUG")
        try:
            relay_setup.apply_config({"TEST_FALSY_VAR": ""})
            assert "TEST_FALSY_VAR" not in os.environ
            assert "Applied relay config: TEST_FALSY_VAR" not in caplog.text
        finally:
            logger.remove(handler_id)

    def test_apply_config_existing_logging(self, caplog, monkeypatch, relay_setup):
        monkeypatch.setenv("TEST_EXISTING_VAR", "old")
        from loguru import logger

        handler_id = logger.add(caplog.handler, format="{message}", level="DEBUG")
        try:
            relay_setup.apply_config({"TEST_EXISTING_VAR": "new"})
            assert os.environ["TEST_EXISTING_VAR"] == "old"
            assert "Applied relay config: TEST_EXISTING_VAR" not in caplog.text
        finally:
            logger.remove(handler_id)


class TestEnsureConfig:
    """Tests for ensure_config."""

    async def test_skips_relay_if_env_vars_present(self, monkeypatch, relay_setup):
        monkeypatch.setenv("GEMINI_API_KEY", "test_key")
        result = await relay_setup.ensure_config()
        assert result is None

    async def test_uses_config_file_if_present(self, relay_setup):
        mock_config = {"GEMINI_API_KEY": "file_key"}
        with (
            patch.object(
                relay_setup, "load_config_from_file", return_value=mock_config
            ),
            patch.object(relay_setup, "apply_config") as mock_apply,
        ):
            result = await relay_setup.ensure_config()
            assert result == mock_config
            mock_apply.assert_called_once_with(mock_config)

    async def test_runtime_error_relay_skipped(self, relay_setup):
        mock_mcp_relay_client = MagicMock()
        mock_mcp_relay_client.create_session = AsyncMock(
            side_effect=RuntimeError("RELAY_SKIPPED")
        )
        with patch.dict(
            "sys.modules", {"mcp_relay_core.relay.client": mock_mcp_relay_client}
        ):
            result = await relay_setup.ensure_config(force=True)
            assert result is None

    async def test_runtime_error_timed_out(self, relay_setup):
        mock_mcp_relay_client = MagicMock()
        mock_mcp_relay_client.create_session = AsyncMock(
            side_effect=RuntimeError("timed out")
        )
        with patch.dict(
            "sys.modules", {"mcp_relay_core.relay.client": mock_mcp_relay_client}
        ):
            result = await relay_setup.ensure_config(force=True)
            assert result is None

    async def test_generic_exception(self, relay_setup):
        mock_mcp_relay_client = MagicMock()
        mock_mcp_relay_client.create_session = AsyncMock(
            side_effect=Exception("random error")
        )
        with patch.dict(
            "sys.modules", {"mcp_relay_core.relay.client": mock_mcp_relay_client}
        ):
            result = await relay_setup.ensure_config(force=True)
            assert result is None


class TestEnsureConfigForced:
    """Tests for ensure_config(force=True) -- manual relay setup."""

    async def test_calls_create_session(self, relay_setup, relay_schema):
        mock_session = MagicMock(
            relay_url="https://example.com/setup/abc",
            session_id="test-session-id",
        )
        mock_config = {"GEMINI_API_KEY": "AIza_test_key"}

        mock_settings = MagicMock()
        mock_settings.google_drive_client_id = "test_client_id"

        mock_mcp_relay_client = MagicMock()
        mock_mcp_relay_storage = MagicMock()

        # Mock setup_google_auth
        mock_sync = MagicMock()
        mock_sync.setup_google_auth = AsyncMock(return_value=True)

        with (
            patch.dict(
                "sys.modules",
                {
                    "wet_mcp.config": MagicMock(settings=mock_settings),
                    "mcp_relay_core.relay.client": mock_mcp_relay_client,
                    "mcp_relay_core.storage.config_file": mock_mcp_relay_storage,
                    "wet_mcp.sync": mock_sync,
                },
            ),
            patch.object(
                mock_mcp_relay_client,
                "create_session",
                new_callable=AsyncMock,
                return_value=mock_session,
            ) as mock_create,
            patch.object(
                mock_mcp_relay_client,
                "poll_for_result",
                new_callable=AsyncMock,
                return_value=mock_config,
            ),
            patch.object(relay_setup, "apply_config"),
            patch("httpx.AsyncClient") as mock_httpx,
        ):
            mock_httpx_inst = AsyncMock()
            mock_httpx.return_value.__aenter__ = AsyncMock(return_value=mock_httpx_inst)
            mock_httpx.return_value.__aexit__ = AsyncMock()

            result = await relay_setup.ensure_config(force=True, timeout=None)

            mock_create.assert_called_once_with(
                relay_setup.DEFAULT_RELAY_URL, "wet-mcp", relay_schema
            )
            assert result == mock_config
            assert mock_httpx_inst.post.call_count >= 1

    async def test_calls_create_session_gdrive_fail(self, relay_setup, relay_schema):
        mock_session = MagicMock(
            relay_url="https://example.com/setup/abc",
            session_id="test-session-id",
        )
        mock_config = {"GEMINI_API_KEY": "AIza_test_key"}

        mock_settings = MagicMock()
        mock_settings.google_drive_client_id = "test_client_id"

        mock_mcp_relay_client = MagicMock()
        mock_mcp_relay_storage = MagicMock()

        # Mock setup_google_auth to fail
        mock_sync = MagicMock()
        mock_sync.setup_google_auth = AsyncMock(side_effect=Exception("GDrive fail"))

        with (
            patch.dict(
                "sys.modules",
                {
                    "wet_mcp.config": MagicMock(settings=mock_settings),
                    "mcp_relay_core.relay.client": mock_mcp_relay_client,
                    "mcp_relay_core.storage.config_file": mock_mcp_relay_storage,
                    "wet_mcp.sync": mock_sync,
                },
            ),
            patch.object(
                mock_mcp_relay_client,
                "create_session",
                new_callable=AsyncMock,
                return_value=mock_session,
            ),
            patch.object(
                mock_mcp_relay_client,
                "poll_for_result",
                new_callable=AsyncMock,
                return_value=mock_config,
            ),
            patch.object(relay_setup, "apply_config"),
            patch("httpx.AsyncClient") as mock_httpx,
        ):
            mock_httpx_inst = AsyncMock()
            mock_httpx.return_value.__aenter__ = AsyncMock(return_value=mock_httpx_inst)
            mock_httpx.return_value.__aexit__ = AsyncMock()

            result = await relay_setup.ensure_config(force=True, timeout=None)
            assert result == mock_config

    async def test_httpx_error_ignored(self, relay_setup, relay_schema):
        mock_session = MagicMock(
            relay_url="https://example.com/setup/abc",
            session_id="test-session-id",
        )
        mock_config = {"GEMINI_API_KEY": "AIza_test_key"}
        mock_settings = MagicMock(google_drive_client_id=None)

        mock_mcp_relay_client = MagicMock()
        mock_mcp_relay_client.create_session = AsyncMock(return_value=mock_session)
        mock_mcp_relay_client.poll_for_result = AsyncMock(return_value=mock_config)

        with (
            patch.dict(
                "sys.modules",
                {
                    "wet_mcp.config": MagicMock(settings=mock_settings),
                    "mcp_relay_core.relay.client": mock_mcp_relay_client,
                    "mcp_relay_core.storage.config_file": MagicMock(),
                },
            ),
            patch.object(relay_setup, "apply_config"),
            patch("httpx.AsyncClient") as mock_httpx,
        ):
            mock_httpx_inst = AsyncMock()
            mock_httpx_inst.post.side_effect = Exception("HTTP error")
            mock_httpx.return_value.__aenter__ = AsyncMock(return_value=mock_httpx_inst)

            result = await relay_setup.ensure_config(force=True, timeout=None)
            assert result == mock_config

    async def test_returns_none_on_exception(self, relay_setup):
        """When relay server is unreachable, returns None."""
        mock_mcp_relay_client = MagicMock()
        with (
            patch.dict(
                "sys.modules",
                {
                    "mcp_relay_core.relay.client": mock_mcp_relay_client,
                },
            ),
            patch.object(
                mock_mcp_relay_client,
                "create_session",
                new_callable=AsyncMock,
                side_effect=ConnectionError("unreachable"),
            ),
        ):
            result = await relay_setup.ensure_config(force=True, timeout=None)
            assert result is None
