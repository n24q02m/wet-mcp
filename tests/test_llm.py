"""Tests for LLM integration."""

import asyncio
from unittest.mock import MagicMock, patch

import pytest

from wet_mcp.config import settings
from wet_mcp.llm import analyze_media, get_llm_config


@pytest.fixture
def mock_settings():
    """Mock settings for testing."""
    original_keys = settings.api_keys
    original_models = settings.llm_models

    settings.api_keys = "gemini:fake-key"
    settings.llm_models = "gemini/fake-model"

    yield

    settings.api_keys = original_keys
    settings.llm_models = original_models


def test_get_llm_config(mock_settings):
    """Test LLM config parsing."""
    config = get_llm_config()
    assert config["model"] == "gemini/fake-model"
    assert config["fallbacks"] is None
    assert config["temperature"] == 0.1


@patch("wet_mcp.llm.completion")
def test_analyze_media(mock_completion, mock_settings, tmp_path):
    """Test analyze_media function using real temp file."""
    # Create valid dummy image file
    img_path = tmp_path / "test.jpg"
    img_path.write_bytes(b"fake-image-data")

    # Mock completion response
    mock_response = MagicMock()
    mock_response.choices[0].message.content = "A nice cat."
    mock_completion.return_value = mock_response

    # Run test
    result = asyncio.run(analyze_media(str(img_path), "Describe"))

    assert result == "A nice cat."

    # Verify completion call
    mock_completion.assert_called_once()
    call_args = mock_completion.call_args[1]
    assert call_args["model"] == "gemini/fake-model"
    assert len(call_args["messages"]) == 1
    assert call_args["messages"][0]["role"] == "user"
    # "fake-image-data" base64 encoded is "ZmFrZS1pbWFnZS1kYXRh"
    assert "ZmFrZS1pbWFnZS1kYXRh" in str(call_args["messages"][0]["content"])


def test_analyze_media_no_keys():
    """Test analyze_media without keys."""
    # Temporarily clear keys
    original_keys = settings.api_keys
    settings.api_keys = None

    result = asyncio.run(analyze_media("test.jpg"))

    settings.api_keys = original_keys
    assert "Error: LLM analysis requires API_KEYS" in result


def test_analyze_media_file_not_found(mock_settings):
    """Test file not found error."""
    result = asyncio.run(analyze_media("non_existent_file.jpg"))
    assert "Error: File not found" in result


def test_analyze_media_invalid_type(mock_settings, tmp_path):
    """Test invalid file type."""
    txt_path = tmp_path / "test.txt"
    txt_path.write_text("Hello")

    result = asyncio.run(analyze_media(str(txt_path)))
    assert "Error: Only image analysis" in result
