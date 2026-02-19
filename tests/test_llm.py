"""Tests for LLM integration."""

import asyncio
from unittest.mock import MagicMock, patch

import pytest
from pydantic import SecretStr

from wet_mcp.config import settings
from wet_mcp.llm import analyze_media, get_llm_config


@pytest.fixture
def mock_settings():
    """Mock settings for testing."""
    original_keys = settings.api_keys
    original_models = settings.llm_models
    original_temperature = settings.llm_temperature

    settings.api_keys = SecretStr("GOOGLE_API_KEY:fake-key")
    settings.llm_models = "gemini/fake-model"
    settings.llm_temperature = None

    yield

    settings.api_keys = original_keys
    settings.llm_models = original_models
    settings.llm_temperature = original_temperature


def test_get_llm_config(mock_settings):
    """Test LLM config parsing."""
    config = get_llm_config()
    assert config["model"] == "gemini/fake-model"
    assert config["fallbacks"] is None
    assert config["temperature"] is None


def test_get_llm_config_with_temperature(mock_settings):
    """Test LLM config with temperature."""
    settings.llm_temperature = 0.7
    config = get_llm_config()
    assert config["temperature"] == 0.7


@patch("wet_mcp.llm.acompletion")
def test_analyze_media(mock_completion, mock_settings, tmp_path):
    """Test analyze_media function using real temp file."""
    # Create valid dummy image file
    img_path = tmp_path / "test.jpg"
    img_path.write_bytes(b"fake-image-data")

    # Mock completion response
    mock_response = MagicMock()
    mock_response.choices[0].message.content = "A nice cat."
    mock_completion.return_value = mock_response

    # Mock capabilities to support vision
    with patch("wet_mcp.llm.get_model_capabilities") as mock_caps:
        mock_caps.return_value = {
            "vision": True,
            "audio_input": False,
            "audio_output": False,
        }

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


@patch("wet_mcp.llm.acompletion")
def test_analyze_media_text_file(mock_completion, mock_settings, tmp_path):
    """Test text file analysis."""
    txt_path = tmp_path / "test.txt"
    txt_path.write_text("Hello")

    # Mock response
    mock_response = MagicMock()
    mock_response.choices[0].message.content = "Summary of text."
    mock_completion.return_value = mock_response

    result = asyncio.run(analyze_media(str(txt_path)))
    assert result == "Summary of text."

    # Verify call structure for text
    mock_completion.assert_called_once()
    call_args = mock_completion.call_args[1]
    assert "File Content:\n```\nHello\n```" in str(call_args["messages"][0]["content"])


def test_analyze_media_unsupported_type(mock_settings, tmp_path):
    """Test unsupported file type."""
    bin_path = tmp_path / "test.bin"
    bin_path.write_bytes(b"\x00\x01")  # unknown binary

    result = asyncio.run(analyze_media(str(bin_path)))
    assert (
        "Error: Cannot determine file type" in result
        or "Unsupported media type" in result
    )
