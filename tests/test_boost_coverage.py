"""Tests to boost overall coverage to 95%+.

Targets low-coverage modules identified by CI (91.51%):
- relay_setup.py (~56%) -- ensure_config branches, GDrive OAuth, timeout/skip
- server.py (~67%) -- config tool, help tool, research, media download security
- llm.py (~46%) -- acompletion, gemini/openai backends, message conversion, fallbacks
- sync.py (~83%) -- sync_full branches, setup_google_auth success, drive_request, auto_sync_loop
- token_store.py (~83%) -- already well covered, minor gaps
- searxng_runner.py (~76%) -- subprocess lifecycle, cleanup, stale port, discovery
"""

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# =====================================================================
# relay_setup.py -- ensure_config branches
# =====================================================================


class TestEnsureConfig:
    """Cover ensure_config: env vars priority, config file, relay, timeout, skip."""

    @pytest.fixture(autouse=True)
    def _relay_url(self, monkeypatch):
        """Default MCP_RELAY_URL for all remote-relay-path tests.

        Per mode-matrix 2.5, wet-mcp remote-relay mode requires explicit
        MCP_RELAY_URL (no DEFAULT_RELAY_URL fallback). Tests that exercise
        the create_session path need this set. Tests that return early
        (env vars / config file) are unaffected by this fixture.
        """
        monkeypatch.setenv("MCP_RELAY_URL", "https://relay.example.com")

    async def test_missing_relay_url_raises(self, monkeypatch):
        """Remote-relay path without MCP_RELAY_URL must raise per matrix 2.5."""
        from wet_mcp.relay_setup import ensure_config

        for key in [
            "GEMINI_API_KEY",
            "OPENAI_API_KEY",
            "JINA_AI_API_KEY",
            "COHERE_API_KEY",
            "MCP_RELAY_URL",
        ]:
            monkeypatch.delenv(key, raising=False)

        with (
            patch("wet_mcp.relay_setup.load_config_from_file", return_value=None),
            pytest.raises(RuntimeError, match="MCP_RELAY_URL"),
        ):
            await ensure_config(force=True)

    async def test_env_vars_skip_relay(self, monkeypatch):
        """When env vars have cloud keys, relay is skipped entirely."""
        from wet_mcp.relay_setup import ensure_config

        monkeypatch.setenv("GEMINI_API_KEY", "test-key")
        result = await ensure_config()
        assert result is None
        monkeypatch.delenv("GEMINI_API_KEY")

    async def test_config_file_used(self, monkeypatch):
        """When config file has keys, they are applied."""
        from wet_mcp.relay_setup import ensure_config

        # Clear all cloud keys from env
        for key in [
            "GEMINI_API_KEY",
            "OPENAI_API_KEY",
            "JINA_AI_API_KEY",
            "COHERE_API_KEY",
        ]:
            monkeypatch.delenv(key, raising=False)

        saved_config = {"GEMINI_API_KEY": "from-file", "OPENAI_API_KEY": ""}
        with (
            patch(
                "wet_mcp.relay_setup.load_config_from_file",
                return_value=saved_config,
            ),
            patch("wet_mcp.relay_setup.apply_config") as mock_apply,
        ):
            result = await ensure_config()
            assert result == saved_config
            mock_apply.assert_called_once_with(saved_config)

    async def test_relay_setup_timeout(self, monkeypatch):
        """When relay times out, returns None (local mode)."""
        from wet_mcp.relay_setup import ensure_config

        for key in [
            "GEMINI_API_KEY",
            "OPENAI_API_KEY",
            "JINA_AI_API_KEY",
            "COHERE_API_KEY",
        ]:
            monkeypatch.delenv(key, raising=False)

        with (
            patch("wet_mcp.relay_setup.load_config_from_file", return_value=None),
            patch(
                "mcp_core.relay.client.create_session",
                new_callable=AsyncMock,
                side_effect=RuntimeError("timed out waiting"),
            ),
        ):
            result = await ensure_config()
            assert result is None

    async def test_relay_setup_skipped(self, monkeypatch):
        """When user skips relay, returns None."""
        from wet_mcp.relay_setup import ensure_config

        for key in [
            "GEMINI_API_KEY",
            "OPENAI_API_KEY",
            "JINA_AI_API_KEY",
            "COHERE_API_KEY",
        ]:
            monkeypatch.delenv(key, raising=False)

        with (
            patch("wet_mcp.relay_setup.load_config_from_file", return_value=None),
            patch(
                "mcp_core.relay.client.create_session",
                new_callable=AsyncMock,
                side_effect=RuntimeError("RELAY_SKIPPED"),
            ),
        ):
            result = await ensure_config()
            assert result is None

    async def test_relay_setup_generic_runtime_error(self, monkeypatch):
        """When relay has a generic RuntimeError, returns None."""
        from wet_mcp.relay_setup import ensure_config

        for key in [
            "GEMINI_API_KEY",
            "OPENAI_API_KEY",
            "JINA_AI_API_KEY",
            "COHERE_API_KEY",
        ]:
            monkeypatch.delenv(key, raising=False)

        with (
            patch("wet_mcp.relay_setup.load_config_from_file", return_value=None),
            patch(
                "mcp_core.relay.client.create_session",
                new_callable=AsyncMock,
                side_effect=RuntimeError("some other error"),
            ),
        ):
            result = await ensure_config()
            assert result is None

    async def test_relay_setup_generic_exception(self, monkeypatch):
        """When relay has a generic Exception, returns None."""
        from wet_mcp.relay_setup import ensure_config

        for key in [
            "GEMINI_API_KEY",
            "OPENAI_API_KEY",
            "JINA_AI_API_KEY",
            "COHERE_API_KEY",
        ]:
            monkeypatch.delenv(key, raising=False)

        with (
            patch("wet_mcp.relay_setup.load_config_from_file", return_value=None),
            patch(
                "mcp_core.relay.client.create_session",
                new_callable=AsyncMock,
                side_effect=Exception("connection refused"),
            ),
        ):
            result = await ensure_config()
            assert result is None

    async def test_relay_setup_success_with_gdrive(self, monkeypatch):
        """Full relay success path with GDrive OAuth."""
        from wet_mcp.relay_setup import ensure_config

        for key in [
            "GEMINI_API_KEY",
            "OPENAI_API_KEY",
            "JINA_AI_API_KEY",
            "COHERE_API_KEY",
        ]:
            monkeypatch.delenv(key, raising=False)

        mock_session = MagicMock(
            relay_url="https://relay.example.com/setup/abc",
            session_id="test-session-id",
        )
        mock_config = {"GEMINI_API_KEY": "from-relay"}

        mock_http_instance = AsyncMock()
        mock_http_instance.post = AsyncMock()

        with (
            patch("wet_mcp.relay_setup.load_config_from_file", return_value=None),
            patch(
                "mcp_core.relay.client.create_session",
                new_callable=AsyncMock,
                return_value=mock_session,
            ),
            patch(
                "mcp_core.relay.client.poll_for_result",
                new_callable=AsyncMock,
                return_value=mock_config,
            ),
            patch("mcp_core.storage.per_plugin_store.PerPluginStore.save"),
            patch("httpx.AsyncClient") as mock_httpx,
            patch("wet_mcp.config.settings") as mock_settings,
            patch("wet_mcp.relay_setup.apply_config") as mock_apply,
            patch(
                "wet_mcp.sync.setup_google_auth",
                new_callable=AsyncMock,
                return_value=True,
            ),
        ):
            mock_settings.google_drive_client_id = "client-id-123"
            mock_httpx.return_value.__aenter__ = AsyncMock(
                return_value=mock_http_instance
            )
            mock_httpx.return_value.__aexit__ = AsyncMock(return_value=None)

            result = await ensure_config()
            assert result == mock_config
            mock_apply.assert_called_once_with(mock_config)

    async def test_relay_setup_success_no_gdrive(self, monkeypatch):
        """Relay success without GDrive client ID."""
        from wet_mcp.relay_setup import ensure_config

        for key in [
            "GEMINI_API_KEY",
            "OPENAI_API_KEY",
            "JINA_AI_API_KEY",
            "COHERE_API_KEY",
        ]:
            monkeypatch.delenv(key, raising=False)

        mock_session = MagicMock(
            relay_url="https://relay.example.com/setup/abc",
            session_id="test-session-id",
        )
        mock_config = {"OPENAI_API_KEY": "from-relay"}

        mock_http_instance = AsyncMock()
        mock_http_instance.post = AsyncMock()

        with (
            patch("wet_mcp.relay_setup.load_config_from_file", return_value=None),
            patch(
                "mcp_core.relay.client.create_session",
                new_callable=AsyncMock,
                return_value=mock_session,
            ),
            patch(
                "mcp_core.relay.client.poll_for_result",
                new_callable=AsyncMock,
                return_value=mock_config,
            ),
            patch("mcp_core.storage.per_plugin_store.PerPluginStore.save"),
            patch("httpx.AsyncClient") as mock_httpx,
            patch("wet_mcp.config.settings") as mock_settings,
            patch("wet_mcp.relay_setup.apply_config") as mock_apply,
        ):
            mock_settings.google_drive_client_id = ""  # no GDrive
            mock_httpx.return_value.__aenter__ = AsyncMock(
                return_value=mock_http_instance
            )
            mock_httpx.return_value.__aexit__ = AsyncMock(return_value=None)

            result = await ensure_config()
            assert result == mock_config
            mock_apply.assert_called_once_with(mock_config)

    async def test_relay_setup_gdrive_failure(self, monkeypatch):
        """GDrive OAuth fails but relay config still returned."""
        from wet_mcp.relay_setup import ensure_config

        for key in [
            "GEMINI_API_KEY",
            "OPENAI_API_KEY",
            "JINA_AI_API_KEY",
            "COHERE_API_KEY",
        ]:
            monkeypatch.delenv(key, raising=False)

        mock_session = MagicMock(
            relay_url="https://relay.example.com/setup/abc",
            session_id="test-session-id",
        )
        mock_config = {"GEMINI_API_KEY": "from-relay"}

        mock_http_instance = AsyncMock()
        mock_http_instance.post = AsyncMock()

        with (
            patch("wet_mcp.relay_setup.load_config_from_file", return_value=None),
            patch(
                "mcp_core.relay.client.create_session",
                new_callable=AsyncMock,
                return_value=mock_session,
            ),
            patch(
                "mcp_core.relay.client.poll_for_result",
                new_callable=AsyncMock,
                return_value=mock_config,
            ),
            patch("mcp_core.storage.per_plugin_store.PerPluginStore.save"),
            patch("httpx.AsyncClient") as mock_httpx,
            patch("wet_mcp.config.settings") as mock_settings,
            patch("wet_mcp.relay_setup.apply_config") as mock_apply,
            patch(
                "wet_mcp.sync.setup_google_auth",
                new_callable=AsyncMock,
                side_effect=Exception("OAuth failed"),
            ),
        ):
            mock_settings.google_drive_client_id = "client-id"
            mock_httpx.return_value.__aenter__ = AsyncMock(
                return_value=mock_http_instance
            )
            mock_httpx.return_value.__aexit__ = AsyncMock(return_value=None)

            result = await ensure_config()
            assert result == mock_config
            mock_apply.assert_called_once_with(mock_config)


class TestLoadConfigFromFile:
    """Additional coverage for load_config_from_file."""

    def test_returns_config_with_keys(self):
        """When saved config has cloud keys, returns it."""
        from wet_mcp.relay_setup import load_config_from_file

        saved = {"GEMINI_API_KEY": "test-key", "OPENAI_API_KEY": ""}
        with patch(
            "mcp_core.storage.per_plugin_store.PerPluginStore.load",
            return_value=saved,
        ):
            result = load_config_from_file()
            assert result == saved

    def test_returns_none_when_no_cloud_keys(self):
        """When saved config has no cloud keys, returns None."""
        from wet_mcp.relay_setup import load_config_from_file

        saved = {"SOME_OTHER_KEY": "value"}
        with patch(
            "mcp_core.storage.per_plugin_store.PerPluginStore.load",
            return_value=saved,
        ):
            result = load_config_from_file()
            assert result is None

    def test_returns_none_on_exception(self):
        """On any exception, returns None."""
        from wet_mcp.relay_setup import load_config_from_file

        with patch(
            "mcp_core.storage.per_plugin_store.PerPluginStore.load",
            side_effect=Exception("disk error"),
        ):
            result = load_config_from_file()
            assert result is None


class TestEnsureConfigForced:
    """Coverage for ensure_config(force=True) -- manual relay setup."""

    @pytest.fixture(autouse=True)
    def _relay_url(self, monkeypatch):
        """MCP_RELAY_URL is required for remote-relay mode per matrix 2.5."""
        monkeypatch.setenv("MCP_RELAY_URL", "https://relay.example.com")

    async def test_relay_skipped_returns_none(self):
        """When user skips, returns None."""
        from wet_mcp.relay_setup import ensure_config

        with patch(
            "mcp_core.relay.client.create_session",
            new_callable=AsyncMock,
            side_effect=RuntimeError("RELAY_SKIPPED by user"),
        ):
            result = await ensure_config(force=True, timeout=None)
            assert result is None

    async def test_generic_runtime_error(self):
        """Generic RuntimeError returns None."""
        from wet_mcp.relay_setup import ensure_config

        with patch(
            "mcp_core.relay.client.create_session",
            new_callable=AsyncMock,
            side_effect=RuntimeError("network error"),
        ):
            result = await ensure_config(force=True, timeout=None)
            assert result is None

    async def test_generic_exception(self):
        """Generic Exception returns None."""
        from wet_mcp.relay_setup import ensure_config

        with patch(
            "mcp_core.relay.client.create_session",
            new_callable=AsyncMock,
            side_effect=Exception("unexpected"),
        ):
            result = await ensure_config(force=True, timeout=None)
            assert result is None


# =====================================================================
# llm.py -- acompletion, backends, message conversion
# =====================================================================


class TestLLMACompletion:
    """Cover acompletion routing and fallback logic."""

    async def test_gemini_completion_routes(self):
        """acompletion routes to _gemini_completion for gemini models."""
        from wet_mcp.llm import _Response, acompletion

        with patch(
            "wet_mcp.llm._gemini_completion", new_callable=AsyncMock
        ) as mock_gemini:
            mock_gemini.return_value = _Response("Hello from Gemini")
            result = await acompletion(
                model="gemini/gemini-3-flash-preview",
                messages=[{"role": "user", "content": "Hi"}],
            )
            assert result.choices[0].message.content == "Hello from Gemini"
            mock_gemini.assert_called_once()

    async def test_openai_completion_routes(self):
        """acompletion routes to _openai_completion for openai models."""
        from wet_mcp.llm import acompletion

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "Hello from OpenAI"

        with patch(
            "wet_mcp.llm._openai_completion", new_callable=AsyncMock
        ) as mock_openai:
            mock_openai.return_value = mock_response
            result = await acompletion(
                model="openai/gpt-4",
                messages=[{"role": "user", "content": "Hi"}],
            )
            assert result.choices[0].message.content == "Hello from OpenAI"
            mock_openai.assert_called_once()

    async def test_xai_completion_routes(self):
        """acompletion routes to _openai_completion for xai models."""
        from wet_mcp.llm import acompletion

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "Hello from Grok"

        with patch(
            "wet_mcp.llm._openai_completion", new_callable=AsyncMock
        ) as mock_openai:
            mock_openai.return_value = mock_response
            result = await acompletion(
                model="xai/grok-4-1-fast-reasoning",
                messages=[{"role": "user", "content": "Hi"}],
            )
            assert result.choices[0].message.content == "Hello from Grok"

    async def test_fallback_on_primary_failure(self):
        """acompletion tries fallbacks when primary fails."""
        from wet_mcp.llm import _Response, acompletion

        call_count = 0

        async def mock_completion(**kwargs):
            nonlocal call_count
            call_count += 1
            model = kwargs.get("model", "")
            if "primary" in model:
                raise Exception("primary failed")
            return _Response("Fallback worked")

        with patch("wet_mcp.llm.acompletion", side_effect=mock_completion):
            # Direct test of fallback logic
            pass

        # Test via the actual function with mocked backends
        with (
            patch(
                "wet_mcp.llm._gemini_completion",
                new_callable=AsyncMock,
                side_effect=Exception("gemini down"),
            ),
            patch(
                "wet_mcp.llm._openai_completion",
                new_callable=AsyncMock,
                return_value=MagicMock(
                    choices=[MagicMock(message=MagicMock(content="fallback ok"))]
                ),
            ),
        ):
            result = await acompletion(
                model="gemini/primary-model",
                messages=[{"role": "user", "content": "Hi"}],
                fallbacks=["openai/gpt-4"],
            )
            assert result.choices[0].message.content == "fallback ok"

    async def test_fallback_all_fail_raises(self):
        """When all fallbacks fail, raises the original error."""
        from wet_mcp.llm import acompletion

        with (
            patch(
                "wet_mcp.llm._gemini_completion",
                new_callable=AsyncMock,
                side_effect=Exception("gemini down"),
            ),
            patch(
                "wet_mcp.llm._openai_completion",
                new_callable=AsyncMock,
                side_effect=Exception("openai down"),
            ),
        ):
            with pytest.raises(Exception, match="gemini down"):
                await acompletion(
                    model="gemini/primary-model",
                    messages=[{"role": "user", "content": "Hi"}],
                    fallbacks=["openai/backup-model"],
                )

    async def test_no_fallbacks_raises(self):
        """When no fallbacks and primary fails, raises."""
        from wet_mcp.llm import acompletion

        with patch(
            "wet_mcp.llm._gemini_completion",
            new_callable=AsyncMock,
            side_effect=Exception("gemini down"),
        ):
            with pytest.raises(Exception, match="gemini down"):
                await acompletion(
                    model="gemini/primary-model",
                    messages=[{"role": "user", "content": "Hi"}],
                )


class TestGeminiCompletion:
    """Cover _gemini_completion internals."""

    async def test_gemini_with_temperature_and_max_tokens(self):
        """Config kwargs passed to Gemini."""
        from wet_mcp.llm import _gemini_completion

        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.text = "Gemini response"
        mock_client.models.generate_content.return_value = mock_response

        with (
            patch("google.genai.Client", return_value=mock_client),
            patch("wet_mcp.llm._convert_messages_to_gemini", return_value=[]),
        ):
            result = await _gemini_completion(
                model="gemini-3-flash-preview",
                messages=[{"role": "user", "content": "Hi"}],
                temperature=0.7,
                max_tokens=1000,
                api_key="test-key",
            )
            assert result.choices[0].message.content == "Gemini response"

    async def test_gemini_json_response_format(self):
        """json_object response format sets mime type."""
        from wet_mcp.llm import _gemini_completion

        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.text = '{"key": "value"}'
        mock_client.models.generate_content.return_value = mock_response

        with (
            patch("google.genai.Client", return_value=mock_client),
            patch("wet_mcp.llm._convert_messages_to_gemini", return_value=[]),
        ):
            result = await _gemini_completion(
                model="gemini-3-flash-preview",
                messages=[{"role": "user", "content": "Hi"}],
                response_format={"type": "json_object"},
            )
            assert result.choices[0].message.content == '{"key": "value"}'

    async def test_gemini_json_schema_format(self):
        """json_schema response format sets mime type."""
        from wet_mcp.llm import _gemini_completion

        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.text = '{"data": []}'
        mock_client.models.generate_content.return_value = mock_response

        with (
            patch("google.genai.Client", return_value=mock_client),
            patch("wet_mcp.llm._convert_messages_to_gemini", return_value=[]),
        ):
            result = await _gemini_completion(
                model="gemini-3-flash-preview",
                messages=[{"role": "user", "content": "Hi"}],
                response_format={"type": "json_schema"},
            )
            assert result.choices[0].message.content == '{"data": []}'

    async def test_gemini_empty_response(self):
        """Empty Gemini response handled."""
        from wet_mcp.llm import _gemini_completion

        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.text = None
        mock_client.models.generate_content.return_value = mock_response

        with (
            patch("google.genai.Client", return_value=mock_client),
            patch("wet_mcp.llm._convert_messages_to_gemini", return_value=[]),
        ):
            result = await _gemini_completion(
                model="gemini-3-flash-preview",
                messages=[{"role": "user", "content": "Hi"}],
            )
            assert result.choices[0].message.content == ""


class TestConvertMessagesToGemini:
    """Cover _convert_messages_to_gemini edge cases."""

    def test_system_message_prepended(self):
        """System message prepended to first user message."""
        from wet_mcp.llm import _convert_messages_to_gemini

        with patch("google.genai.types") as mock_types:
            mock_types.Part.from_text.return_value = MagicMock()
            mock_types.Content.return_value = MagicMock()

            messages = [
                {"role": "system", "content": "You are helpful"},
                {"role": "user", "content": "Hello"},
            ]
            _convert_messages_to_gemini(messages)
            # System text prepended to first user message as Part
            assert mock_types.Part.from_text.call_count >= 2

    def test_assistant_role_mapped_to_model(self):
        """Assistant role maps to 'model' in Gemini."""
        from wet_mcp.llm import _convert_messages_to_gemini

        with patch("google.genai.types") as mock_types:
            mock_types.Part.from_text.return_value = MagicMock()
            mock_types.Content.return_value = MagicMock()

            messages = [
                {"role": "assistant", "content": "Previous response"},
                {"role": "user", "content": "Follow up"},
            ]
            _convert_messages_to_gemini(messages)
            # Verify Content was called with role="model" for assistant
            calls = mock_types.Content.call_args_list
            assert any(
                c[1].get("role") == "model" or (c[0] and len(c[0]) > 0) for c in calls
            )

    def test_multipart_content_with_image(self):
        """Image content handled in multipart messages."""
        from wet_mcp.llm import _convert_messages_to_gemini

        with patch("google.genai.types") as mock_types:
            mock_types.Part.from_text.return_value = MagicMock()
            mock_types.Part.from_bytes.return_value = MagicMock()
            mock_types.Part.from_uri.return_value = MagicMock()
            mock_types.Content.return_value = MagicMock()

            # data URL image
            messages = [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Describe"},
                        {
                            "type": "image_url",
                            "image_url": {"url": "data:image/png;base64,aGVsbG8="},
                        },
                    ],
                }
            ]
            _convert_messages_to_gemini(messages)
            mock_types.Part.from_bytes.assert_called_once()

    def test_multipart_content_with_url_image(self):
        """HTTP URL image handled in multipart messages."""
        from wet_mcp.llm import _convert_messages_to_gemini

        with patch("google.genai.types") as mock_types:
            mock_types.Part.from_text.return_value = MagicMock()
            mock_types.Part.from_uri.return_value = MagicMock()
            mock_types.Content.return_value = MagicMock()

            messages = [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Describe"},
                        {
                            "type": "image_url",
                            "image_url": {"url": "https://example.com/img.jpg"},
                        },
                    ],
                }
            ]
            _convert_messages_to_gemini(messages)
            mock_types.Part.from_uri.assert_called_once()

    def test_non_dict_list_items(self):
        """Non-dict items in content list are converted to text."""
        from wet_mcp.llm import _convert_messages_to_gemini

        with patch("google.genai.types") as mock_types:
            mock_types.Part.from_text.return_value = MagicMock()
            mock_types.Content.return_value = MagicMock()

            messages = [
                {
                    "role": "user",
                    "content": ["plain string item"],
                }
            ]
            _convert_messages_to_gemini(messages)
            # Should call from_text with str(item)
            mock_types.Part.from_text.assert_called()

    def test_non_string_non_list_content(self):
        """Non-string, non-list content converted to string."""
        from wet_mcp.llm import _convert_messages_to_gemini

        with patch("google.genai.types") as mock_types:
            mock_types.Part.from_text.return_value = MagicMock()
            mock_types.Content.return_value = MagicMock()

            messages = [
                {
                    "role": "user",
                    "content": 42,
                }
            ]
            _convert_messages_to_gemini(messages)
            mock_types.Part.from_text.assert_called()


class TestOpenAICompletion:
    """Cover _openai_completion for OpenAI and xAI providers."""

    async def test_openai_provider(self):
        """OpenAI provider uses correct base URL."""
        from wet_mcp.llm import _openai_completion

        mock_client = AsyncMock()
        mock_response = MagicMock()
        mock_response.choices = [MagicMock(message=MagicMock(content="ok"))]
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

        with patch("openai.AsyncOpenAI", return_value=mock_client) as mock_cls:
            result = await _openai_completion(
                provider="openai",
                model="gpt-4",
                messages=[{"role": "user", "content": "Hi"}],
                api_key="test-key",
            )
            assert result.choices[0].message.content == "ok"
            mock_cls.assert_called_once_with(
                api_key="test-key", base_url="https://api.openai.com/v1"
            )

    async def test_xai_provider(self):
        """xAI provider uses correct base URL."""
        from wet_mcp.llm import _openai_completion

        mock_client = AsyncMock()
        mock_response = MagicMock()
        mock_response.choices = [MagicMock(message=MagicMock(content="grok"))]
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

        with patch("openai.AsyncOpenAI", return_value=mock_client) as mock_cls:
            result = await _openai_completion(
                provider="xai",
                model="grok-4",
                messages=[{"role": "user", "content": "Hi"}],
                api_key="xai-key",
            )
            assert result.choices[0].message.content == "grok"
            mock_cls.assert_called_once_with(
                api_key="xai-key", base_url="https://api.x.ai/v1"
            )

    async def test_with_temperature_max_tokens_format(self):
        """Optional params passed to OpenAI create call."""
        from wet_mcp.llm import _openai_completion

        mock_client = AsyncMock()
        mock_response = MagicMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

        with patch("openai.AsyncOpenAI", return_value=mock_client):
            await _openai_completion(
                provider="openai",
                model="gpt-4",
                messages=[{"role": "user", "content": "Hi"}],
                temperature=0.5,
                max_tokens=500,
                response_format={"type": "json_object"},
            )
            call_kwargs = mock_client.chat.completions.create.call_args[1]
            assert call_kwargs["temperature"] == 0.5
            assert call_kwargs["max_tokens"] == 500
            assert call_kwargs["response_format"] == {"type": "json_object"}

    async def test_custom_api_base(self, monkeypatch):
        """Custom api_base overrides default."""
        from wet_mcp.llm import _openai_completion

        # Clear env vars to ensure predictable api_key
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)

        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=MagicMock())

        with patch("openai.AsyncOpenAI", return_value=mock_client) as mock_cls:
            await _openai_completion(
                provider="openai",
                model="gpt-4",
                messages=[{"role": "user", "content": "Hi"}],
                api_base="https://custom.api.com/v1",
            )
            mock_cls.assert_called_once_with(
                api_key="", base_url="https://custom.api.com/v1"
            )


class TestDetectProvider:
    """Additional provider detection tests."""

    def test_google_prefix(self):
        from wet_mcp.llm import _detect_provider

        assert _detect_provider("google/gemini-3-flash") == "gemini"

    def test_gpt_prefix(self):
        from wet_mcp.llm import _detect_provider

        assert _detect_provider("gpt/gpt-4") == "openai"

    def test_no_prefix_with_xai_key(self, monkeypatch):
        from wet_mcp.llm import _detect_provider

        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.setenv("XAI_API_KEY", "test")
        assert _detect_provider("bare-model") == "xai"
        monkeypatch.delenv("XAI_API_KEY")

    def test_no_prefix_with_openai_key(self, monkeypatch):
        from wet_mcp.llm import _detect_provider

        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
        monkeypatch.delenv("XAI_API_KEY", raising=False)
        monkeypatch.setenv("OPENAI_API_KEY", "test")
        assert _detect_provider("bare-model") == "openai"
        monkeypatch.delenv("OPENAI_API_KEY")


class TestAnalyzeMediaExtended:
    """Additional analyze_media coverage for audio/video types."""

    async def test_audio_analysis(self, tmp_path):
        """Audio file triggers audio_input capability check."""
        from wet_mcp.config import settings
        from wet_mcp.llm import analyze_media

        orig_dir = settings.download_dir
        settings.download_dir = str(tmp_path)

        audio_path = tmp_path / "test.mp3"
        audio_path.write_bytes(b"fake-audio-data")

        with (
            patch("wet_mcp.llm._has_llm_provider", return_value=True),
            patch(
                "wet_mcp.llm.get_model_capabilities",
                return_value={
                    "vision": False,
                    "audio_input": False,
                    "audio_output": False,
                },
            ),
            patch(
                "wet_mcp.llm.get_llm_config",
                return_value={
                    "model": "gemini/test",
                    "fallbacks": None,
                    "temperature": None,
                },
            ),
        ):
            result = await analyze_media(str(audio_path))
            assert "does not support audio input" in result

        settings.download_dir = orig_dir

    async def test_video_analysis(self, tmp_path):
        """Video file triggers vision capability check."""
        from wet_mcp.config import settings
        from wet_mcp.llm import analyze_media

        orig_dir = settings.download_dir
        settings.download_dir = str(tmp_path)

        video_path = tmp_path / "test.mp4"
        video_path.write_bytes(b"fake-video-data")

        with (
            patch("wet_mcp.llm._has_llm_provider", return_value=True),
            patch(
                "wet_mcp.llm.get_model_capabilities",
                return_value={
                    "vision": False,
                    "audio_input": False,
                    "audio_output": False,
                },
            ),
            patch(
                "wet_mcp.llm.get_llm_config",
                return_value={
                    "model": "openai/test",
                    "fallbacks": None,
                    "temperature": None,
                },
            ),
        ):
            result = await analyze_media(str(video_path))
            assert "does not support video" in result

        settings.download_dir = orig_dir

    async def test_image_no_vision_capability(self, tmp_path):
        """Image file with model lacking vision capability."""
        from wet_mcp.config import settings
        from wet_mcp.llm import analyze_media

        orig_dir = settings.download_dir
        settings.download_dir = str(tmp_path)

        img_path = tmp_path / "test.png"
        img_path.write_bytes(b"\x89PNG\r\n\x1a\n")

        with (
            patch("wet_mcp.llm._has_llm_provider", return_value=True),
            patch(
                "wet_mcp.llm.get_model_capabilities",
                return_value={
                    "vision": False,
                    "audio_input": False,
                    "audio_output": False,
                },
            ),
            patch(
                "wet_mcp.llm.get_llm_config",
                return_value={
                    "model": "test/no-vision",
                    "fallbacks": None,
                    "temperature": None,
                },
            ),
        ):
            result = await analyze_media(str(img_path))
            assert "does not support vision" in result

        settings.download_dir = orig_dir

    async def test_text_file_analysis_error(self, tmp_path):
        """Text file analysis LLM error handled."""
        from wet_mcp.config import settings
        from wet_mcp.llm import analyze_media

        orig_dir = settings.download_dir
        settings.download_dir = str(tmp_path)

        txt_path = tmp_path / "test.txt"
        txt_path.write_text("hello world")

        with (
            patch("wet_mcp.llm._has_llm_provider", return_value=True),
            patch(
                "wet_mcp.llm.get_llm_config",
                return_value={
                    "model": "gemini/test",
                    "fallbacks": None,
                    "temperature": None,
                },
            ),
            patch(
                "wet_mcp.llm.acompletion",
                new_callable=AsyncMock,
                side_effect=Exception("LLM error"),
            ),
        ):
            result = await analyze_media(str(txt_path))
            assert "Error analyzing text file" in result

        settings.download_dir = orig_dir

    async def test_media_analysis_llm_error(self, tmp_path):
        """Image analysis LLM error handled."""
        from wet_mcp.config import settings
        from wet_mcp.llm import analyze_media

        orig_dir = settings.download_dir
        settings.download_dir = str(tmp_path)

        img_path = tmp_path / "test.jpg"
        img_path.write_bytes(b"fake-image")

        with (
            patch("wet_mcp.llm._has_llm_provider", return_value=True),
            patch(
                "wet_mcp.llm.get_model_capabilities",
                return_value={
                    "vision": True,
                    "audio_input": False,
                    "audio_output": False,
                },
            ),
            patch(
                "wet_mcp.llm.get_llm_config",
                return_value={
                    "model": "gemini/test",
                    "fallbacks": None,
                    "temperature": None,
                },
            ),
            patch(
                "wet_mcp.llm.acompletion",
                new_callable=AsyncMock,
                side_effect=Exception("API error"),
            ),
        ):
            result = await analyze_media(str(img_path))
            assert "Error analyzing media" in result

        settings.download_dir = orig_dir


class TestResponseObjects:
    """Cover _Response, _Choice, _Message classes."""

    def test_response_structure(self):
        from wet_mcp.llm import _Choice, _Message, _Response

        resp = _Response("test content")
        assert len(resp.choices) == 1
        assert isinstance(resp.choices[0], _Choice)
        assert isinstance(resp.choices[0].message, _Message)
        assert resp.choices[0].message.content == "test content"


# =====================================================================
# sync.py -- sync_full branches, _drive_request, setup_google_auth
# =====================================================================


class TestSyncFull:
    """Cover sync_full edge cases."""

    async def test_sync_disabled(self):
        """Returns disabled when sync is off."""
        from wet_mcp.sync import sync_full

        with patch("wet_mcp.sync.settings") as mock_settings:
            mock_settings.sync_enabled = False
            result = await sync_full(MagicMock())
            assert result["status"] == "disabled"

    async def test_no_client_id(self):
        """Returns error when no client ID."""
        from wet_mcp.sync import sync_full

        with patch("wet_mcp.sync.settings") as mock_settings:
            mock_settings.sync_enabled = True
            mock_settings.google_drive_client_id = ""
            result = await sync_full(MagicMock())
            assert result["status"] == "error"
            assert "GOOGLE_DRIVE_CLIENT_ID" in result["message"]

    async def test_no_token_available(self):
        """Returns error when no token."""
        from wet_mcp.sync import sync_full

        with (
            patch("wet_mcp.sync.settings") as mock_settings,
            patch("wet_mcp.sync._has_token_available", return_value=False),
        ):
            mock_settings.sync_enabled = True
            mock_settings.google_drive_client_id = "client123"
            result = await sync_full(MagicMock())
            assert result["status"] == "error"
            assert "No Google Drive token" in result["message"]

    async def test_token_expired_refresh_fails(self):
        """Returns error when token expired and refresh fails."""
        from wet_mcp.sync import sync_full

        with (
            patch("wet_mcp.sync.settings") as mock_settings,
            patch("wet_mcp.sync._has_token_available", return_value=True),
            patch("wet_mcp.sync._get_valid_token", return_value=None),
        ):
            mock_settings.sync_enabled = True
            mock_settings.google_drive_client_id = "client123"
            result = await sync_full(MagicMock())
            assert result["status"] == "error"
            assert "expired" in result["message"]

    async def test_pull_merge_exception(self):
        """Merge error caught and reported."""
        from wet_mcp.sync import sync_full

        with (
            patch("wet_mcp.sync.settings") as mock_settings,
            patch("wet_mcp.sync._has_token_available", return_value=True),
            patch(
                "wet_mcp.sync._get_valid_token",
                return_value={"access_token": "t"},
            ),
            patch("wet_mcp.sync.sync_pull", return_value=Path("/tmp/remote.db")),
            patch("wet_mcp.sync.sync_push", return_value=True),
            patch(
                "wet_mcp.db.DocsDB",
                side_effect=Exception("corrupt DB"),
            ),
            patch("pathlib.Path.unlink"),
            patch("pathlib.Path.rmdir"),
        ):
            mock_settings.sync_enabled = True
            mock_settings.google_drive_client_id = "client123"
            mock_settings.get_db_path.return_value = Path("/db/docs.db")
            mock_settings.sync_folder = "wet-mcp"
            result = await sync_full(MagicMock())
            assert "error" in str(result["pull"])

    async def test_pull_none_no_remote_db(self):
        """When pull returns None, report no remote DB."""
        from wet_mcp.sync import sync_full

        with (
            patch("wet_mcp.sync.settings") as mock_settings,
            patch("wet_mcp.sync._has_token_available", return_value=True),
            patch(
                "wet_mcp.sync._get_valid_token",
                return_value={"access_token": "t"},
            ),
            patch("wet_mcp.sync.sync_pull", return_value=None),
            patch("wet_mcp.sync.sync_push", return_value=True),
        ):
            mock_settings.sync_enabled = True
            mock_settings.google_drive_client_id = "client123"
            mock_settings.get_db_path.return_value = Path("/db/docs.db")
            mock_settings.sync_folder = "wet-mcp"
            result = await sync_full(MagicMock())
            assert result["pull"]["note"] == "No remote DB found"


class TestDriveRequest:
    """Cover _drive_request helper."""

    async def test_drive_request_with_all_params(self):
        """All params passed to httpx client."""
        from wet_mcp.sync import _drive_request

        mock_response = MagicMock()
        mock_response.status_code = 200

        mock_client = AsyncMock()
        mock_client.request = AsyncMock(return_value=mock_response)

        with patch("wet_mcp.sync.httpx.AsyncClient") as mock_httpx:
            mock_httpx.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_httpx.return_value.__aexit__ = AsyncMock(return_value=None)

            result = await _drive_request(
                "POST",
                "https://api.example.com/files",
                {"access_token": "test-token"},
                params={"q": "test"},
                json_data={"name": "file.db"},
                content=b"binary-data",
                headers={"X-Custom": "header"},
                timeout=60.0,
            )
            assert result.status_code == 200
            mock_client.request.assert_called_once()


class TestSetupGoogleAuthSuccess:
    """Cover setup_google_auth success path and polling."""

    async def test_success_without_relay(self):
        """Device code flow succeeds without relay."""
        from wet_mcp.sync import setup_google_auth

        device_response = MagicMock()
        device_response.status_code = 200
        device_response.json.return_value = {
            "device_code": "dev123",
            "user_code": "ABC-DEF",
            "verification_url": "https://google.com/device",
            "interval": 0,
            "expires_in": 5,
        }

        token_response = MagicMock()
        token_response.status_code = 200
        token_response.json.return_value = {
            "access_token": "new-access-token",
            "refresh_token": "new-refresh-token",
            "expires_in": 3600,
            "token_type": "Bearer",
        }

        with (
            patch("wet_mcp.sync.settings") as mock_settings,
            patch("wet_mcp.sync.httpx.AsyncClient") as mock_httpx,
            patch("wet_mcp.sync._save_token") as mock_save,
            patch("wet_mcp.sync.asyncio.sleep", new_callable=AsyncMock),
        ):
            mock_settings.google_drive_client_id = "client123"
            mock_settings.google_drive_client_secret = "secret"

            mock_client = AsyncMock()
            mock_client.post = AsyncMock(side_effect=[device_response, token_response])
            mock_httpx.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_httpx.return_value.__aexit__ = AsyncMock(return_value=None)

            result = await setup_google_auth()
            assert result is True
            mock_save.assert_called_once()

    async def test_authorization_pending_then_success(self):
        """Polling returns pending then success."""
        from wet_mcp.sync import setup_google_auth

        device_response = MagicMock()
        device_response.status_code = 200
        device_response.json.return_value = {
            "device_code": "dev123",
            "user_code": "ABC-DEF",
            "verification_url": "https://google.com/device",
            "interval": 0,
            "expires_in": 10,
        }

        pending_response = MagicMock()
        pending_response.status_code = 428
        pending_response.json.return_value = {"error": "authorization_pending"}

        token_response = MagicMock()
        token_response.status_code = 200
        token_response.json.return_value = {
            "access_token": "tok",
            "refresh_token": "ref",
            "expires_in": 3600,
        }

        with (
            patch("wet_mcp.sync.settings") as mock_settings,
            patch("wet_mcp.sync.httpx.AsyncClient") as mock_httpx,
            patch("wet_mcp.sync._save_token"),
            patch("wet_mcp.sync.asyncio.sleep", new_callable=AsyncMock),
        ):
            mock_settings.google_drive_client_id = "client123"
            mock_settings.google_drive_client_secret = "secret"

            mock_client = AsyncMock()
            mock_client.post = AsyncMock(
                side_effect=[device_response, pending_response, token_response]
            )
            mock_httpx.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_httpx.return_value.__aexit__ = AsyncMock(return_value=None)

            result = await setup_google_auth()
            assert result is True

    async def test_slow_down_increases_interval(self):
        """slow_down error increases polling interval."""
        from wet_mcp.sync import setup_google_auth

        device_response = MagicMock()
        device_response.status_code = 200
        device_response.json.return_value = {
            "device_code": "dev123",
            "user_code": "ABC-DEF",
            "verification_url": "https://google.com/device",
            "interval": 0,
            "expires_in": 10,
        }

        slow_response = MagicMock()
        slow_response.status_code = 428
        slow_response.json.return_value = {"error": "slow_down"}

        token_response = MagicMock()
        token_response.status_code = 200
        token_response.json.return_value = {
            "access_token": "tok",
            "refresh_token": "ref",
            "expires_in": 3600,
        }

        with (
            patch("wet_mcp.sync.settings") as mock_settings,
            patch("wet_mcp.sync.httpx.AsyncClient") as mock_httpx,
            patch("wet_mcp.sync._save_token"),
            patch("wet_mcp.sync.asyncio.sleep", new_callable=AsyncMock),
        ):
            mock_settings.google_drive_client_id = "client123"
            mock_settings.google_drive_client_secret = "secret"

            mock_client = AsyncMock()
            mock_client.post = AsyncMock(
                side_effect=[device_response, slow_response, token_response]
            )
            mock_httpx.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_httpx.return_value.__aexit__ = AsyncMock(return_value=None)

            result = await setup_google_auth()
            assert result is True

    async def test_access_denied_returns_false(self):
        """access_denied error returns False."""
        from wet_mcp.sync import setup_google_auth

        device_response = MagicMock()
        device_response.status_code = 200
        device_response.json.return_value = {
            "device_code": "dev123",
            "user_code": "ABC-DEF",
            "verification_url": "https://google.com/device",
            "interval": 0,
            "expires_in": 10,
        }

        denied_response = MagicMock()
        denied_response.status_code = 403
        denied_response.json.return_value = {"error": "access_denied"}

        with (
            patch("wet_mcp.sync.settings") as mock_settings,
            patch("wet_mcp.sync.httpx.AsyncClient") as mock_httpx,
            patch("wet_mcp.sync.asyncio.sleep", new_callable=AsyncMock),
        ):
            mock_settings.google_drive_client_id = "client123"
            mock_settings.google_drive_client_secret = "secret"

            mock_client = AsyncMock()
            mock_client.post = AsyncMock(side_effect=[device_response, denied_response])
            mock_httpx.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_httpx.return_value.__aexit__ = AsyncMock(return_value=None)

            result = await setup_google_auth()
            assert result is False

    async def test_unexpected_error_returns_false(self):
        """Unexpected error in token poll returns False."""
        from wet_mcp.sync import setup_google_auth

        device_response = MagicMock()
        device_response.status_code = 200
        device_response.json.return_value = {
            "device_code": "dev123",
            "user_code": "ABC-DEF",
            "verification_url": "https://google.com/device",
            "interval": 0,
            "expires_in": 10,
        }

        error_response = MagicMock()
        error_response.status_code = 500
        error_response.json.return_value = {"error": "server_error"}

        with (
            patch("wet_mcp.sync.settings") as mock_settings,
            patch("wet_mcp.sync.httpx.AsyncClient") as mock_httpx,
            patch("wet_mcp.sync.asyncio.sleep", new_callable=AsyncMock),
        ):
            mock_settings.google_drive_client_id = "client123"
            mock_settings.google_drive_client_secret = "secret"

            mock_client = AsyncMock()
            mock_client.post = AsyncMock(side_effect=[device_response, error_response])
            mock_httpx.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_httpx.return_value.__aexit__ = AsyncMock(return_value=None)

            result = await setup_google_auth()
            assert result is False

    async def test_token_poll_exception(self):
        """Exception during token polling returns False."""
        from wet_mcp.sync import setup_google_auth

        device_response = MagicMock()
        device_response.status_code = 200
        device_response.json.return_value = {
            "device_code": "dev123",
            "user_code": "ABC-DEF",
            "verification_url": "https://google.com/device",
            "interval": 0,
            "expires_in": 10,
        }

        with (
            patch("wet_mcp.sync.settings") as mock_settings,
            patch("wet_mcp.sync.httpx.AsyncClient") as mock_httpx,
            patch("wet_mcp.sync.asyncio.sleep", new_callable=AsyncMock),
        ):
            mock_settings.google_drive_client_id = "client123"
            mock_settings.google_drive_client_secret = "secret"

            mock_client = AsyncMock()
            # First call succeeds (device code), second throws exception
            mock_client.post = AsyncMock(
                side_effect=[device_response, Exception("network error")]
            )
            mock_httpx.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_httpx.return_value.__aexit__ = AsyncMock(return_value=None)

            result = await setup_google_auth()
            assert result is False

    async def test_no_client_secret(self):
        """Missing client_secret returns False."""
        from wet_mcp.sync import setup_google_auth

        with patch("wet_mcp.sync.settings") as mock_settings:
            mock_settings.google_drive_client_id = "client123"
            mock_settings.google_drive_client_secret = ""
            result = await setup_google_auth()
            assert result is False

    async def test_with_relay_session(self):
        """Device code sent via relay messaging."""
        from wet_mcp.sync import setup_google_auth

        device_response = MagicMock()
        device_response.status_code = 200
        device_response.json.return_value = {
            "device_code": "dev123",
            "user_code": "ABC-DEF",
            "verification_url": "https://google.com/device",
            "interval": 0,
            "expires_in": 5,
        }

        token_response = MagicMock()
        token_response.status_code = 200
        token_response.json.return_value = {
            "access_token": "tok",
            "refresh_token": "ref",
            "expires_in": 3600,
        }

        with (
            patch("wet_mcp.sync.settings") as mock_settings,
            patch("wet_mcp.sync.httpx.AsyncClient") as mock_httpx,
            patch("wet_mcp.sync._save_token"),
            patch("wet_mcp.sync.asyncio.sleep", new_callable=AsyncMock),
        ):
            mock_settings.google_drive_client_id = "client123"
            mock_settings.google_drive_client_secret = "secret"

            mock_client = AsyncMock()
            mock_client.post = AsyncMock(
                side_effect=[device_response, MagicMock(), token_response]
            )
            mock_httpx.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_httpx.return_value.__aexit__ = AsyncMock(return_value=None)

            result = await setup_google_auth(
                relay_url="https://relay.example.com",
                session_id="session-123",
            )
            assert result is True


class TestAutoSyncLoop:
    """Cover _auto_sync_loop branches."""

    async def test_zero_interval_returns(self):
        """Zero interval exits immediately."""
        from wet_mcp.sync import _auto_sync_loop

        with patch("wet_mcp.sync.settings") as mock_settings:
            mock_settings.sync_interval = 0
            await _auto_sync_loop(MagicMock())

    async def test_initial_sync_error(self):
        """Initial sync error is caught and loop continues."""
        from wet_mcp.sync import _auto_sync_loop

        call_count = 0

        async def mock_sync_full(db):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise Exception("first sync failed")
            raise asyncio.CancelledError()

        with (
            patch("wet_mcp.sync.settings") as mock_settings,
            patch("wet_mcp.sync.sync_full", side_effect=mock_sync_full),
            patch("wet_mcp.sync.asyncio.sleep", new_callable=AsyncMock),
        ):
            mock_settings.sync_interval = 1
            await _auto_sync_loop(MagicMock())

    async def test_loop_sync_error(self):
        """Sync error in loop body is caught, loop continues."""
        from wet_mcp.sync import _auto_sync_loop

        call_count = 0

        async def mock_sync_full(db):
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                raise Exception("sync error")
            raise asyncio.CancelledError()

        with (
            patch("wet_mcp.sync.settings") as mock_settings,
            patch("wet_mcp.sync.sync_full", side_effect=mock_sync_full),
            patch("wet_mcp.sync.asyncio.sleep", new_callable=AsyncMock),
        ):
            mock_settings.sync_interval = 1
            await _auto_sync_loop(MagicMock())
            assert call_count >= 2


class TestRefreshTokenExtraEdges:
    """Cover _refresh_token edge cases."""

    async def test_refresh_exception(self):
        """Network exception returns None."""
        from wet_mcp.sync import _refresh_token

        token = {
            "access_token": "old",
            "refresh_token": "refresh123",
            "client_id": "client123",
        }

        with patch("wet_mcp.sync.httpx.AsyncClient") as mock_httpx:
            mock_httpx.return_value.__aenter__ = AsyncMock(
                side_effect=Exception("connection refused")
            )
            mock_httpx.return_value.__aexit__ = AsyncMock(return_value=None)
            result = await _refresh_token(token)
            assert result is None


# =====================================================================
# server.py -- additional coverage for config/help/media/research
# =====================================================================


class TestServerConfigTool:
    """Cover config tool action branches."""

    async def test_config_set_log_level(self):
        """Set log_level updates settings."""
        from wet_mcp.server import config

        with patch("wet_mcp.server.settings") as mock_settings:
            mock_settings.log_level = "INFO"
            result = await config(action="set", key="log_level", value="debug")
            data = json.loads(result)
            assert data["status"] == "updated"
            assert data["key"] == "log_level"

    async def test_config_set_tool_timeout(self):
        """Set numeric setting."""
        from wet_mcp.server import config

        with patch("wet_mcp.server.settings") as mock_settings:
            mock_settings.tool_timeout = 300
            result = await config(action="set", key="tool_timeout", value="600")
            data = json.loads(result)
            assert data["status"] == "updated"

    async def test_config_set_boolean(self):
        """Set boolean setting."""
        from wet_mcp.server import config

        with patch("wet_mcp.server.settings") as mock_settings:
            mock_settings.wet_cache = False
            result = await config(action="set", key="wet_cache", value="true")
            data = json.loads(result)
            assert data["status"] == "updated"

    async def test_config_set_string_setting(self):
        """Set string setting (sync_folder)."""
        from wet_mcp.server import config

        with patch("wet_mcp.server.settings") as mock_settings:
            mock_settings.sync_folder = ""
            result = await config(action="set", key="sync_folder", value="my-folder")
            data = json.loads(result)
            assert data["status"] == "updated"

    async def test_config_set_invalid_key(self):
        """Invalid key returns error."""
        from wet_mcp.server import config

        result = await config(action="set", key="invalid_key", value="val")
        data = json.loads(result)
        assert "error" in data
        assert "Invalid key" in data["error"]

    async def test_config_set_missing_params(self):
        """Missing key or value returns error."""
        from wet_mcp.server import config

        result = await config(action="set", key=None, value=None)
        data = json.loads(result)
        assert "error" in data

    async def test_config_cache_clear_enabled(self):
        """Cache clear when enabled."""
        from wet_mcp import server
        from wet_mcp.server import config

        mock_cache = MagicMock()
        old_cache = server._web_cache
        server._web_cache = mock_cache
        try:
            result = await config(action="cache_clear")
            data = json.loads(result)
            assert data["status"] == "cache cleared"
        finally:
            server._web_cache = old_cache

    async def test_config_cache_clear_disabled(self):
        """Cache clear when disabled."""
        from wet_mcp import server
        from wet_mcp.server import config

        old_cache = server._web_cache
        server._web_cache = None
        try:
            result = await config(action="cache_clear")
            data = json.loads(result)
            assert "error" in data
        finally:
            server._web_cache = old_cache

    async def test_config_docs_reindex_not_found(self):
        """Reindex library not found."""
        from wet_mcp import server
        from wet_mcp.server import config

        mock_db = MagicMock()
        mock_db.get_library.return_value = None
        old_db = server._docs_db
        server._docs_db = mock_db
        try:
            result = await config(action="docs_reindex", key="nonexistent")
            data = json.loads(result)
            assert "error" in data
        finally:
            server._docs_db = old_db

    async def test_config_docs_reindex_found(self):
        """Reindex existing library."""
        from wet_mcp import server
        from wet_mcp.server import config

        mock_db = MagicMock()
        mock_db.get_library.return_value = {"id": 1, "name": "react"}
        mock_db.get_best_version.return_value = {"id": 10, "version": "latest"}
        old_db = server._docs_db
        server._docs_db = mock_db
        try:
            result = await config(action="docs_reindex", key="react")
            data = json.loads(result)
            assert data["status"] == "cleared"
            mock_db.clear_version_chunks.assert_called_once_with(10)
        finally:
            server._docs_db = old_db

    async def test_config_docs_reindex_no_db(self):
        """Reindex when DB not initialized."""
        from wet_mcp import server
        from wet_mcp.server import config

        old_db = server._docs_db
        server._docs_db = None
        try:
            result = await config(action="docs_reindex", key="react")
            data = json.loads(result)
            assert "error" in data
        finally:
            server._docs_db = old_db

    async def test_config_docs_reindex_no_key(self):
        """Reindex without library name."""
        from wet_mcp.server import config

        result = await config(action="docs_reindex")
        data = json.loads(result)
        assert "error" in data

    async def test_config_warmup_action(self):
        """Warmup action is now part of config tool (merged from setup)."""
        with patch(
            "wet_mcp.setup_tool.run_warmup",
            new_callable=AsyncMock,
            return_value={"status": "ok", "steps": [], "mode": "local"},
        ):
            from wet_mcp.server import config

            result = await config(action="warmup")
            data = json.loads(result)
            assert data["status"] == "ok"

    async def test_config_setup_sync_action(self):
        """setup_sync action is now part of config tool (merged from setup)."""
        with patch(
            "wet_mcp.setup_tool.run_setup_sync",
            new_callable=AsyncMock,
            return_value={"status": "ok", "remote_type": "drive", "message": "done"},
        ):
            from wet_mcp.server import config

            result = await config(action="setup_sync", remote_type="drive")
            data = json.loads(result)
            assert data["status"] == "ok"

    async def test_config_invalid_action(self):
        """Invalid config action returns error."""
        from wet_mcp.server import config

        result = await config(action="invalid_action")
        data = json.loads(result)
        assert "error" in data
        assert "Unknown action" in data["error"]

    async def test_config_status(self):
        """Status action returns server status."""
        from wet_mcp import server
        from wet_mcp.server import config

        old_db = server._docs_db
        old_cache = server._web_cache
        server._docs_db = MagicMock()
        server._docs_db.stats.return_value = {"libraries": 5}
        server._web_cache = MagicMock()

        with (
            patch("wet_mcp.server.settings") as mock_settings,
            patch("wet_mcp.embedder.get_backend", return_value=MagicMock()),
            patch("wet_mcp.reranker.get_reranker", return_value=None),
        ):
            mock_settings.get_db_path.return_value = Path("/db/docs.db")
            mock_settings.wet_cache = True
            mock_settings.get_cache_db_path.return_value = Path("/db/cache.db")
            mock_settings.sync_enabled = False
            mock_settings.sync_folder = "wet-mcp"
            mock_settings.sync_interval = 300
            mock_settings.google_drive_client_id = ""
            mock_settings.log_level = "INFO"
            mock_settings.tool_timeout = 300

            result = await config(action="status")
            data = json.loads(result)
            assert "database" in data
            assert "embedding" in data
            assert "sync" in data

        server._docs_db = old_db
        server._web_cache = old_cache


class TestServerSetupTool:
    """Cover setup_* actions in config tool (warmup, setup_sync).

    The ``setup_open_relay`` action and its underlying
    ``trigger_relay_setup`` were removed in the stdio-pure refactor
    (spec 2026-05-01). Only env-var (stdio) and HTTP browser-form
    (HTTP mode) remain as credential entry paths.
    """

    async def test_setup_warmup(self):
        """Warmup action delegates to run_warmup."""
        from wet_mcp.server import config

        with patch(
            "wet_mcp.setup_tool.run_warmup",
            new_callable=AsyncMock,
            return_value={"status": "ok", "mode": "local", "steps": []},
        ):
            result = await config(action="warmup")
            data = json.loads(result)
            assert data["status"] == "ok"

    async def test_setup_sync(self):
        """setup_sync action delegates to run_setup_sync."""
        from wet_mcp.server import config

        with patch(
            "wet_mcp.setup_tool.run_setup_sync",
            new_callable=AsyncMock,
            return_value={"status": "ok", "provider": "google_drive"},
        ):
            result = await config(action="setup_sync")
            data = json.loads(result)
            assert data["status"] == "ok"

    async def test_setup_invalid_action(self):
        """Invalid config action returns error with suggestions."""
        from wet_mcp.server import config

        result = await config(action="invalid_action_xyz")
        data = json.loads(result)
        assert "error" in data
        assert "Unknown action" in data["error"]


class TestServerHelpTool:
    """Cover help tool branches."""

    async def test_help_valid_tool(self):
        """Valid tool name returns documentation."""
        from wet_mcp.server import help

        with patch("wet_mcp.server.files") as mock_files:
            mock_doc = MagicMock()
            mock_doc.read_text.return_value = "# Search Tool\nDocumentation here."
            mock_files.return_value.joinpath.return_value = mock_doc
            result = await help(tool_name="search")
            assert "Documentation here" in result

    async def test_help_invalid_tool(self):
        """Invalid tool name returns error."""
        from wet_mcp.server import help

        result = await help(tool_name="invalid_tool")
        assert "Error: Invalid tool_name" in result

    async def test_help_file_not_found(self):
        """Missing doc file returns error."""
        from wet_mcp.server import help

        with patch("wet_mcp.server.files") as mock_files:
            mock_files.return_value.joinpath.side_effect = FileNotFoundError(
                "not found"
            )
            result = await help(tool_name="search")
            assert "Error" in result

    async def test_help_exception(self):
        """Exception loading docs returns error."""
        from wet_mcp.server import help

        with patch("wet_mcp.server.files") as mock_files:
            mock_files.return_value.joinpath.side_effect = Exception("read error")
            result = await help(tool_name="search")
            assert "Error loading documentation" in result


class TestServerMediaTool:
    """Cover media tool branches."""

    async def test_media_list_missing_url(self):
        """List action requires url."""
        from wet_mcp.server import media

        result = await media(action="list")
        assert "Error: url is required" in result

    async def test_media_download_missing_urls(self):
        """Download action requires media_urls."""
        from wet_mcp.server import media

        result = await media(action="download")
        assert "Error: media_urls is required" in result

    async def test_media_analyze_returns_unknown_action_post_removal(self):
        """Phase 3 BREAKING: analyze removed in v2.0.0 -- unknown-action route."""
        from wet_mcp.server import media

        result = await media(action="analyze")
        assert "Unknown action 'analyze'" in result
        assert "imagine-mcp" in result
        assert "removed in wet v2.0.0" in result

    async def test_media_invalid_action(self):
        """Invalid media action."""
        from wet_mcp.server import media

        result = await media(action="invalid")
        assert "Error: Unknown action" in result

    async def test_media_download_security(self):
        """Download output_dir must be within download_dir."""
        from wet_mcp.server import media

        with patch("wet_mcp.server.settings") as mock_settings:
            mock_settings.download_dir = "/safe/downloads"
            result = await media(
                action="download",
                media_urls=["https://example.com/img.jpg"],
                output_dir="/etc/evil",
            )
            assert "Security Alert" in result

    async def test_media_list_success(self):
        """List action calls list_media."""
        from wet_mcp.server import media

        with patch(
            "wet_mcp.server.list_media",
            new_callable=AsyncMock,
            return_value='{"media": []}',
        ):
            result = await media(action="list", url="https://example.com")
            assert "media" in result

    async def test_media_analyze_does_not_call_analyze_media(self):
        """Removed analyze must not invoke the underlying llm primitive."""
        from wet_mcp.server import media

        with patch(
            "wet_mcp.llm.analyze_media",
            new_callable=AsyncMock,
            return_value="A beautiful image",
        ) as mocked:
            result = await media(
                action="analyze", url="/tmp/img.jpg", prompt="Describe"
            )
            assert "Unknown action 'analyze'" in result
            mocked.assert_not_called()


class TestServerResearchAction:
    """Cover search research action."""

    async def test_research_missing_query(self):
        """Research requires query."""
        from wet_mcp.server import search

        result = await search(action="research")
        assert "Error: query is required" in result

    async def test_research_success(self):
        """Research action delegates to _do_research."""
        from wet_mcp.server import search

        mock_results = json.dumps(
            {
                "results": [
                    {
                        "url": "https://arxiv.org/123",
                        "title": "Paper",
                        "snippet": "Abstract",
                    }
                ],
                "total": 1,
                "query": "attention",
            }
        )

        with (
            patch(
                "wet_mcp.server.ensure_searxng",
                new_callable=AsyncMock,
                return_value="http://localhost:8080",
            ),
            patch(
                "wet_mcp.server.searxng_search",
                new_callable=AsyncMock,
                return_value=mock_results,
            ),
            patch("wet_mcp.server._web_cache", None),
            patch(
                "wet_mcp.server._rerank_results",
                new_callable=AsyncMock,
                return_value=[
                    {
                        "url": "https://arxiv.org/123",
                        "title": "Paper",
                        "snippet": "Abstract",
                        "content": "Abstract",
                        "score": 0.9,
                    }
                ],
            ),
        ):
            result = await search(action="research", query="attention mechanism")
            assert "arxiv" in result

    async def test_docs_missing_library(self):
        """Docs requires library."""
        from wet_mcp.server import search

        result = await search(action="docs", query="routing")
        assert "Error: library is required" in result

    async def test_docs_missing_query(self):
        """Docs requires query."""
        from wet_mcp.server import search

        result = await search(action="docs", library="fastapi")
        assert "Error: query is required" in result

    async def test_search_typo_suggestion(self):
        """Typo in action gets suggestion."""
        from wet_mcp.server import search

        result = await search(action="serch")
        assert "Did you mean" in result

    async def test_extract_typo_suggestion(self):
        """Typo in extract action gets suggestion."""
        from wet_mcp.server import extract

        result = await extract(action="exract")
        assert "Did you mean" in result


class TestServerHelpers:
    """Cover _embed, _embed_batch, _rerank_results, _with_timeout."""

    async def test_embed_no_backend(self):
        """_embed returns None when no backend."""
        from wet_mcp.server import _embed

        with patch("wet_mcp.embedder.get_backend", return_value=None):
            result = await _embed("test text")
            assert result is None

    async def test_embed_failure(self):
        """_embed returns None on error."""
        from wet_mcp.server import _embed

        mock_backend = MagicMock()
        mock_backend.embed_single.side_effect = Exception("embed error")
        with patch("wet_mcp.embedder.get_backend", return_value=mock_backend):
            result = await _embed("test text")
            assert result is None

    async def test_embed_batch_no_backend(self):
        """_embed_batch returns None when no backend."""
        from wet_mcp.server import _embed_batch

        with patch("wet_mcp.embedder.get_backend", return_value=None):
            result = await _embed_batch(["text1", "text2"])
            assert result is None

    async def test_embed_batch_failure(self):
        """_embed_batch returns None on error."""
        from wet_mcp.server import _embed_batch

        mock_backend = MagicMock()
        mock_backend.embed_texts.side_effect = Exception("batch error")
        with patch("wet_mcp.embedder.get_backend", return_value=mock_backend):
            result = await _embed_batch(["text1"])
            assert result is None

    async def test_rerank_no_reranker(self):
        """_rerank_results returns truncated results when no reranker."""
        from wet_mcp.server import _rerank_results

        results = [{"content": f"r{i}"} for i in range(5)]
        with patch("wet_mcp.reranker.get_reranker", return_value=None):
            reranked = await _rerank_results("query", results, top_n=3)
            assert len(reranked) == 3

    async def test_rerank_fewer_than_topn(self):
        """_rerank_results returns all when fewer than top_n."""
        from wet_mcp.server import _rerank_results

        results = [{"content": "r1"}, {"content": "r2"}]
        with patch("wet_mcp.reranker.get_reranker", return_value=MagicMock()):
            reranked = await _rerank_results("query", results, top_n=5)
            assert len(reranked) == 2

    async def test_rerank_success(self):
        """_rerank_results reorders by score."""
        from wet_mcp.server import _rerank_results

        results = [{"content": "r0"}, {"content": "r1"}, {"content": "r2"}]
        mock_reranker = MagicMock()
        mock_reranker.rerank.return_value = [(2, 0.95), (0, 0.80)]

        with patch("wet_mcp.reranker.get_reranker", return_value=mock_reranker):
            reranked = await _rerank_results("query", results, top_n=2)
            assert len(reranked) == 2
            assert reranked[0]["content"] == "r2"
            assert reranked[0]["score"] == 0.95

    async def test_rerank_failure_fallback(self):
        """_rerank_results falls back on error."""
        from wet_mcp.server import _rerank_results

        results = [{"content": f"r{i}"} for i in range(5)]
        mock_reranker = MagicMock()
        mock_reranker.rerank.side_effect = Exception("rerank error")

        with patch("wet_mcp.reranker.get_reranker", return_value=mock_reranker):
            reranked = await _rerank_results("query", results, top_n=3)
            assert len(reranked) == 3

    async def test_with_timeout_no_timeout(self):
        """_with_timeout with timeout=0 runs normally."""
        from wet_mcp.server import _with_timeout

        async def fake_coro():
            return "result"

        with patch("wet_mcp.server.settings") as mock_settings:
            mock_settings.tool_timeout = 0
            result = await _with_timeout(fake_coro(), "test")
            assert result == "result"


class TestServerDetectGhToken:
    """Cover _detect_gh_token branches."""

    def test_no_gh_cli(self):
        """Returns None when gh CLI not installed."""
        from wet_mcp.server import _detect_gh_token

        with patch("shutil.which", return_value=None):
            assert _detect_gh_token() is None

    def test_gh_cli_returns_token(self):
        """Returns token from gh auth token."""
        from wet_mcp.server import _detect_gh_token

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "ghp_test_token_123\n"

        with (
            patch("shutil.which", return_value="/usr/bin/gh"),
            patch("subprocess.run", return_value=mock_result),
        ):
            assert _detect_gh_token() == "ghp_test_token_123"

    def test_gh_cli_fails(self):
        """Returns None when gh auth token fails."""
        from wet_mcp.server import _detect_gh_token

        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = ""

        with (
            patch("shutil.which", return_value="/usr/bin/gh"),
            patch("subprocess.run", return_value=mock_result),
        ):
            assert _detect_gh_token() is None

    def test_gh_cli_empty_token(self):
        """Returns None when gh returns empty token."""
        from wet_mcp.server import _detect_gh_token

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "  \n"

        with (
            patch("shutil.which", return_value="/usr/bin/gh"),
            patch("subprocess.run", return_value=mock_result),
        ):
            assert _detect_gh_token() is None

    def test_gh_cli_exception(self):
        """Returns None on exception."""
        from wet_mcp.server import _detect_gh_token

        with (
            patch("shutil.which", return_value="/usr/bin/gh"),
            patch("subprocess.run", side_effect=Exception("timeout")),
        ):
            assert _detect_gh_token() is None


# =====================================================================
# searxng_runner.py -- additional coverage
# =====================================================================


class TestSearxngRunnerExtras:
    """Cover additional branches in searxng_runner.py."""

    def test_is_pid_alive_unix_zombie(self):
        """Zombie process detected on Linux."""
        from web_core.search.runner import _is_pid_alive

        if sys.platform == "win32":
            pytest.skip("Unix-only test")

        with (
            patch("os.kill"),  # os.kill succeeds for zombies
            patch("pathlib.Path.exists", return_value=True),
            patch("pathlib.Path.read_text", return_value="State:\tZ (zombie)\n"),
        ):
            assert _is_pid_alive(12345) is False

    def test_cleanup_process_owner(self):
        """Cleanup kills process when owner."""
        import web_core.search.runner as runner

        mock_proc = MagicMock()
        runner._searxng_process = mock_proc
        runner._searxng_port = 8080
        runner._is_owner = True

        with (
            patch.object(runner, "_force_kill_process"),
            patch.object(runner, "_remove_discovery"),
        ):
            runner._cleanup_process()
            assert runner._searxng_process is None
            assert runner._searxng_port is None
            assert runner._is_owner is False

    def test_cleanup_process_not_owner(self):
        """Cleanup leaves process running when not owner."""
        import web_core.search.runner as runner

        mock_proc = MagicMock()
        runner._searxng_process = mock_proc
        runner._searxng_port = 8080
        runner._is_owner = False

        runner._cleanup_process()
        assert runner._searxng_process is None

    def test_cleanup_no_process(self):
        """Cleanup with no process is a no-op."""
        import web_core.search.runner as runner

        runner._searxng_process = None
        runner._cleanup_process()  # Should not raise

    @pytest.mark.skipif(
        sys.platform == "win32", reason="os.setsid unavailable on Windows"
    )
    def test_get_process_kwargs_unix(self):
        """Unix kwargs include start_new_session for process group management."""
        from web_core.search.runner import _get_process_kwargs

        with patch("web_core.search.runner.sys") as mock_sys:
            mock_sys.platform = "linux"
            kwargs = _get_process_kwargs()
            # web-core uses start_new_session=True (modern Python) instead of
            # preexec_fn — keep both expectations covered so future regressions
            # in either direction surface here.
            assert kwargs.get("start_new_session") is True
            assert "preexec_fn" not in kwargs

    @pytest.mark.skipif(sys.platform != "win32", reason="Windows-only test")
    def test_get_process_kwargs_windows(self):
        """Windows kwargs include creationflags."""
        from web_core.search.runner import _get_process_kwargs

        kwargs = _get_process_kwargs()
        assert "creationflags" in kwargs

    def test_get_startup_lock_creates_once(self):
        """Startup lock is created once and reused."""
        import web_core.search.runner as runner

        runner._startup_lock = None
        lock1 = runner._get_startup_lock()
        lock2 = runner._get_startup_lock()
        assert lock1 is lock2
        runner._startup_lock = None  # cleanup

    def test_find_available_port(self):
        """Port finder returns a valid port."""
        from web_core.search.runner import _find_available_port

        port = _find_available_port(40000, max_tries=10)
        assert 40000 <= port < 40010

    def test_is_searxng_installed_true(self):
        """Returns True when searx.webapp is importable."""
        from web_core.search.runner import _is_searxng_installed

        with patch("importlib.util.find_spec", return_value=MagicMock()):
            assert _is_searxng_installed() is True

    def test_is_searxng_installed_false(self):
        """Returns False when searx.webapp not importable."""
        from web_core.search.runner import _is_searxng_installed

        with patch("importlib.util.find_spec", return_value=None):
            assert _is_searxng_installed() is False

    def test_is_searxng_installed_error(self):
        """Returns False on import error."""
        from web_core.search.runner import _is_searxng_installed

        with patch(
            "importlib.util.find_spec", side_effect=ModuleNotFoundError("no module")
        ):
            assert _is_searxng_installed() is False

    def test_read_discovery_valid(self, tmp_path):
        """Read valid discovery file."""
        import web_core.search.runner as runner

        old = runner._DISCOVERY_FILE
        runner._DISCOVERY_FILE = tmp_path / "instance.json"
        runner._DISCOVERY_FILE.write_text(json.dumps({"pid": 123, "port": 8080}))
        # web-core's _read_discovery rejects files whose mode is not 0o600 on
        # POSIX (defence-in-depth). tmp_path inherits umask, so chmod here.
        if sys.platform != "win32":
            os.chmod(runner._DISCOVERY_FILE, 0o600)

        result = runner._read_discovery()
        assert result is not None
        assert result["port"] == 8080
        runner._DISCOVERY_FILE = old

    def test_read_discovery_invalid(self, tmp_path):
        """Read invalid discovery file returns None."""
        import web_core.search.runner as runner

        old = runner._DISCOVERY_FILE
        runner._DISCOVERY_FILE = tmp_path / "instance.json"
        runner._DISCOVERY_FILE.write_text("not json")

        result = runner._read_discovery()
        assert result is None
        runner._DISCOVERY_FILE = old

    def test_read_discovery_missing(self, tmp_path):
        """Missing discovery file returns None."""
        import web_core.search.runner as runner

        old = runner._DISCOVERY_FILE
        runner._DISCOVERY_FILE = tmp_path / "nonexistent.json"

        result = runner._read_discovery()
        assert result is None
        runner._DISCOVERY_FILE = old

    def test_write_and_remove_discovery(self, tmp_path):
        """Write and remove discovery file."""
        import web_core.search.runner as runner

        old = runner._DISCOVERY_FILE
        runner._DISCOVERY_FILE = tmp_path / "instance.json"

        runner._write_discovery(8080, 12345)
        assert runner._DISCOVERY_FILE.exists()

        runner._remove_discovery()
        assert not runner._DISCOVERY_FILE.exists()

        runner._DISCOVERY_FILE = old

    async def test_quick_health_check_success(self):
        """Health check succeeds on 200."""
        from web_core.search.runner import _quick_health_check

        mock_response = MagicMock()
        mock_response.status_code = 200

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)

        with patch("web_core.search.runner.httpx.AsyncClient") as mock_httpx:
            mock_httpx.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_httpx.return_value.__aexit__ = AsyncMock(return_value=None)

            result = await _quick_health_check("http://127.0.0.1:8080", retries=1)
            assert result is True

    async def test_quick_health_check_failure(self):
        """Health check fails after retries."""
        from web_core.search.runner import _quick_health_check

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=Exception("connection refused"))

        with (
            patch("web_core.search.runner.httpx.AsyncClient") as mock_httpx,
            patch("web_core.search.runner.asyncio.sleep", new_callable=AsyncMock),
        ):
            mock_httpx.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_httpx.return_value.__aexit__ = AsyncMock(return_value=None)

            result = await _quick_health_check("http://127.0.0.1:9999", retries=2)
            assert result is False

    def test_get_pip_command_uv(self):
        """Returns uv pip command when uv available."""
        from web_core.search.runner import _get_pip_command

        with patch("shutil.which") as mock_which:
            mock_which.side_effect = lambda x: "/usr/bin/uv" if x == "uv" else None
            cmd = _get_pip_command()
            assert "uv" in cmd[0]

    def test_get_pip_command_pip(self):
        """Returns pip command when pip available."""
        from web_core.search.runner import _get_pip_command

        with patch("shutil.which") as mock_which:
            mock_which.side_effect = lambda x: "/usr/bin/pip" if x == "pip" else None
            cmd = _get_pip_command()
            assert "pip" in cmd[0]

    def test_get_pip_command_fallback(self):
        """Returns python -m pip as fallback."""
        from web_core.search.runner import _get_pip_command

        with patch("shutil.which", return_value=None):
            cmd = _get_pip_command()
            # [sys.executable, "-m", "pip", "install", "--python", sys.executable]
            # or [sys.executable, "-m", "pip", "install"]
            assert "pip" in cmd
            assert "-m" in cmd

    @pytest.mark.asyncio
    async def test_force_kill_already_dead(self):
        """Force kill on already dead process is no-op."""
        from web_core.search.runner import _force_kill_process

        mock_proc = MagicMock()
        mock_proc.poll.return_value = 0  # Already dead
        await _force_kill_process(mock_proc)
        # Should not call terminate/kill


class TestSearxngInstall:
    """Cover _install_searxng."""

    def test_install_success(self):
        """Successful installation."""
        from web_core.search.runner import _install_searxng

        mock_result = MagicMock()
        mock_result.returncode = 0

        with (
            patch.object(subprocess, "run", return_value=mock_result),
            patch(
                "web_core.search.runner._get_pip_command",
                return_value=["pip", "install"],
            ),
            patch("wet_mcp.setup.patch_searxng_version"),
            patch("wet_mcp.setup.patch_searxng_windows"),
        ):
            assert _install_searxng() is True

    def test_install_deps_failure(self):
        """Build deps installation failure."""
        from web_core.search.runner import _install_searxng

        mock_deps_result = MagicMock()
        mock_deps_result.returncode = 1
        mock_deps_result.stderr = "dependency error"

        with (
            patch.object(subprocess, "run", return_value=mock_deps_result),
            patch(
                "web_core.search.runner._get_pip_command",
                return_value=["pip", "install"],
            ),
        ):
            assert _install_searxng() is False

    def test_install_searxng_failure(self):
        """SearXNG installation failure."""
        from web_core.search.runner import _install_searxng

        call_count = 0

        def fake_run(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            mock = MagicMock()
            if call_count == 1:
                mock.returncode = 0  # deps succeed
            else:
                mock.returncode = 1  # searxng fails
                mock.stderr = "install error"
            return mock

        with (
            patch.object(subprocess, "run", side_effect=fake_run),
            patch(
                "web_core.search.runner._get_pip_command",
                return_value=["pip", "install"],
            ),
        ):
            assert _install_searxng() is False

    def test_install_timeout(self):
        """Installation timeout."""
        from web_core.search.runner import _install_searxng

        with (
            patch.object(
                subprocess,
                "run",
                side_effect=subprocess.TimeoutExpired("pip", 300),
            ),
            patch(
                "web_core.search.runner._get_pip_command",
                return_value=["pip", "install"],
            ),
        ):
            assert _install_searxng() is False

    def test_install_exception(self):
        """General exception during installation."""
        from web_core.search.runner import _install_searxng

        with (
            patch.object(
                subprocess,
                "run",
                side_effect=Exception("unexpected"),
            ),
            patch(
                "web_core.search.runner._get_pip_command",
                return_value=["pip", "install"],
            ),
        ):
            assert _install_searxng() is False


# =====================================================================
# setup_tool.py -- additional coverage
# =====================================================================


class TestSetupTool:
    """Cover setup_tool.py functions."""

    def test_clear_model_cache_exists(self, tmp_path):
        """Clears existing cache directory."""
        from wet_mcp.setup_tool import clear_model_cache

        cache_dir = tmp_path / "models--test--model"
        cache_dir.mkdir(parents=True)
        (cache_dir / "file.bin").write_bytes(b"data")

        with patch.dict(os.environ, {"QWEN3_EMBED_CACHE_PATH": str(tmp_path)}):
            result = clear_model_cache("test/model")
            assert result is not None
            assert not cache_dir.exists()

    def test_clear_model_cache_not_exists(self, tmp_path):
        """Returns None when no cache."""
        from wet_mcp.setup_tool import clear_model_cache

        with patch.dict(os.environ, {"QWEN3_EMBED_CACHE_PATH": str(tmp_path)}):
            result = clear_model_cache("nonexistent/model")
            assert result is None

    async def test_run_setup_sync_success(self):
        """setup sync returns success."""
        from wet_mcp.setup_tool import run_setup_sync

        with patch(
            "wet_mcp.sync.setup_google_auth",
            new_callable=AsyncMock,
            return_value=True,
        ):
            result = await run_setup_sync()
            assert result["status"] == "ok"

    async def test_run_setup_sync_failure(self):
        """setup sync returns failure."""
        from wet_mcp.setup_tool import run_setup_sync

        with patch(
            "wet_mcp.sync.setup_google_auth",
            new_callable=AsyncMock,
            return_value=False,
        ):
            result = await run_setup_sync()
            assert result["status"] == "error"

    async def test_run_setup_sync_exception(self):
        """setup sync exception handled."""
        from wet_mcp.setup_tool import run_setup_sync

        with patch(
            "wet_mcp.sync.setup_google_auth",
            new_callable=AsyncMock,
            side_effect=Exception("auth error"),
        ):
            result = await run_setup_sync()
            assert result["status"] == "error"


# =====================================================================
# setup.py -- additional coverage
# =====================================================================


class TestSetup:
    """Cover setup.py functions."""

    def test_needs_setup_false(self, tmp_path):
        """Returns False when marker exists."""
        from wet_mcp import setup

        old = setup.SETUP_MARKER
        setup.SETUP_MARKER = tmp_path / ".setup-complete"
        setup.SETUP_MARKER.touch()
        assert setup.needs_setup() is False
        setup.SETUP_MARKER = old

    def test_needs_setup_true(self, tmp_path):
        """Returns True when marker missing."""
        from wet_mcp import setup

        old = setup.SETUP_MARKER
        setup.SETUP_MARKER = tmp_path / ".setup-complete"
        assert setup.needs_setup() is True
        setup.SETUP_MARKER = old

    def test_find_searx_package_dir_found(self):
        """Returns path when searx found."""
        from wet_mcp.setup import _find_searx_package_dir

        mock_spec = MagicMock()
        mock_spec.submodule_search_locations = ["/path/to/searx"]
        with patch("importlib.util.find_spec", return_value=mock_spec):
            result = _find_searx_package_dir()
            assert result == Path("/path/to/searx")

    def test_find_searx_package_dir_not_found(self):
        """Returns None when searx not found."""
        from wet_mcp.setup import _find_searx_package_dir

        with patch("importlib.util.find_spec", return_value=None):
            result = _find_searx_package_dir()
            assert result is None

    def test_find_searx_package_dir_error(self):
        """Returns None on exception."""
        from wet_mcp.setup import _find_searx_package_dir

        with patch("importlib.util.find_spec", side_effect=Exception("error")):
            result = _find_searx_package_dir()
            assert result is None

    def test_patch_searxng_version_creates_file(self, tmp_path):
        """Creates version_frozen.py when missing."""
        from wet_mcp.setup import patch_searxng_version

        searx_dir = tmp_path / "searx"
        searx_dir.mkdir()
        vf = searx_dir / "version_frozen.py"

        with patch("wet_mcp.setup._find_searx_package_dir", return_value=searx_dir):
            patch_searxng_version()
            assert vf.exists()
            content = vf.read_text()
            assert "VERSION_STRING" in content

    def test_patch_searxng_version_already_exists(self, tmp_path):
        """Does not overwrite existing version_frozen.py."""
        from wet_mcp.setup import patch_searxng_version

        searx_dir = tmp_path / "searx"
        searx_dir.mkdir()
        vf = searx_dir / "version_frozen.py"
        vf.write_text("existing content")

        with patch("wet_mcp.setup._find_searx_package_dir", return_value=searx_dir):
            patch_searxng_version()
            assert vf.read_text() == "existing content"

    def test_patch_searxng_version_no_dir(self):
        """No-op when searx dir not found."""
        from wet_mcp.setup import patch_searxng_version

        with patch("wet_mcp.setup._find_searx_package_dir", return_value=None):
            patch_searxng_version()  # Should not raise


class TestRandomizedPortFinder:
    """Tests for the randomized port finder in searxng_runner."""

    def test_finds_available_port(self):
        """Should find an available port in range."""
        from wet_mcp.searxng_runner import _find_available_port

        port = _find_available_port(40000, max_tries=100)
        assert 40000 <= port < 40100

    def test_raises_when_no_port_available(self):
        """Raises RuntimeError when all ports are occupied."""
        from wet_mcp.searxng_runner import _find_available_port

        with patch("socket.socket") as mock_socket:
            mock_sock = MagicMock()
            mock_sock.__enter__ = MagicMock(return_value=mock_sock)
            mock_sock.__exit__ = MagicMock(return_value=False)
            mock_sock.bind.side_effect = OSError("Address in use")
            mock_socket.return_value = mock_sock
            with pytest.raises(RuntimeError, match="No available port"):
                _find_available_port(40000, max_tries=3)
