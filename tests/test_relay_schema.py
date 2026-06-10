"""Tests for relay schema definition."""

import pytest
from pydantic import ValidationError

from wet_mcp.relay_schema import RELAY_SCHEMA, ConfigData


class TestRelaySchema:
    """Tests for relay schema definition."""

    def test_schema_has_flat_fields(self):
        """Schema uses flat fields structure (not modes)."""
        assert "fields" in RELAY_SCHEMA
        assert "modes" not in RELAY_SCHEMA

    def test_schema_has_five_provider_fields(self):
        fields = RELAY_SCHEMA["fields"]
        assert len(fields) == 5

    def test_schema_field_keys(self):
        field_keys = [f["key"] for f in RELAY_SCHEMA["fields"]]
        assert "JINA_AI_API_KEY" in field_keys
        assert "GEMINI_API_KEY" in field_keys
        assert "OPENAI_API_KEY" in field_keys
        assert "COHERE_API_KEY" in field_keys
        assert "GITHUB_TOKEN" in field_keys

    def test_schema_server_name(self):
        assert RELAY_SCHEMA["server"] == "wet-mcp"

    def test_schema_display_name(self):
        assert RELAY_SCHEMA["displayName"] == "Web Extended Toolkit"

    def test_all_fields_optional(self):
        for f in RELAY_SCHEMA["fields"]:
            assert f.get("required") is False

    def test_capability_info_present(self):
        assert "capabilityInfo" in RELAY_SCHEMA
        assert len(RELAY_SCHEMA["capabilityInfo"]) == 5
        labels = [c["label"] for c in RELAY_SCHEMA["capabilityInfo"]]
        assert "Search" in labels
        assert "Extraction" in labels
        assert "Embedding" in labels
        assert "Reranking" in labels
        assert "LLM" in labels


class TestConfigData:
    """Tests for ConfigData Pydantic model."""

    def test_config_data_valid_token(self):
        """Verify successful instantiation with a token string."""
        config = ConfigData(token="test_token")
        assert config.token == "test_token"

    def test_config_data_invalid_token(self):
        """Verify that a missing token triggers a Pydantic validation error."""
        with pytest.raises(ValidationError):
            ConfigData()  # type: ignore
