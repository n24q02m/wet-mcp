"""Tests for LLM integration."""

import asyncio
import os
from unittest.mock import MagicMock, patch

import pytest
from pydantic import SecretStr

from wet_mcp.config import settings
from wet_mcp.llm import (
    _AUDIO_INPUT_MODELS,
    _VISION_MODELS,
    _detect_provider,
    _has_llm_provider,
    _read_and_truncate,
    _strip_provider,
    acompletion,
    analyze_media,
    encode_image,
    get_llm_config,
    get_model_capabilities,
)


@pytest.fixture
def mock_settings():
    """Mock settings for testing."""
    original_keys = settings.api_keys
    original_models = settings.llm_models
    original_temperature = settings.llm_temperature
    original_download_dir = settings.download_dir

    settings.api_keys = SecretStr("GOOGLE_API_KEY:fake-key")
    settings.llm_models = "gemini/fake-model"
    settings.llm_temperature = None

    yield

    settings.api_keys = original_keys
    settings.llm_models = original_models
    settings.llm_temperature = original_temperature
    settings.download_dir = original_download_dir


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


def test_get_llm_config_fallbacks(mock_settings):
    """Test LLM config with fallbacks."""
    settings.llm_models = "gemini/fake-model, openai/gpt-4"
    config = get_llm_config()
    assert config["model"] == "gemini/fake-model"
    assert config["fallbacks"] == ["openai/gpt-4"]


def test_get_llm_config_empty_models(mock_settings):
    """Test LLM config with empty or whitespace models string."""
    settings.llm_models = "   ,  "
    config = get_llm_config()
    assert config["model"] == "gemini/gemini-3-flash-preview"
    assert config["fallbacks"] is None


def test_get_llm_config_basic_structure(mock_settings):
    """Test LLM config returns basic structure without custom endpoints."""
    config = get_llm_config()
    assert "model" in config
    assert "fallbacks" in config
    assert "temperature" in config
    assert "api_base" not in config
    assert "api_key" not in config


@patch("wet_mcp.llm.acompletion")
def test_analyze_media(mock_completion, mock_settings, tmp_path):
    """Test analyze_media function using real temp file."""
    # Point download_dir to tmp_path so path traversal check passes
    settings.download_dir = str(tmp_path)

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

        # Also mock _has_llm_provider to return True
        with patch("wet_mcp.llm._has_llm_provider", return_value=True):
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


def test_analyze_media_no_keys(tmp_path):
    """Test analyze_media without keys."""
    # Temporarily clear keys
    original_keys = settings.api_keys
    settings.api_keys = None
    settings.download_dir = str(tmp_path)

    img_path = tmp_path / "test.jpg"
    img_path.touch()

    with patch.dict(os.environ, {}, clear=True):
        result = asyncio.run(analyze_media(str(img_path)))

    settings.api_keys = original_keys
    assert "Error: LLM analysis requires API keys" in result


def test_analyze_media_file_not_found(mock_settings, tmp_path):
    """Test file not found error."""
    settings.download_dir = str(tmp_path)
    with patch("wet_mcp.llm._has_llm_provider", return_value=True):
        result = asyncio.run(analyze_media(str(tmp_path / "non_existent_file.jpg")))
    assert "Error: Access denied or file not found" in result


@patch("wet_mcp.llm.acompletion")
def test_analyze_media_text_file(mock_completion, mock_settings, tmp_path):
    """Test text file analysis."""
    settings.download_dir = str(tmp_path)

    txt_path = tmp_path / "test.txt"
    txt_path.write_text("Hello")

    # Mock response
    mock_response = MagicMock()
    mock_response.choices[0].message.content = "Summary of text."
    mock_completion.return_value = mock_response

    with patch("wet_mcp.llm._has_llm_provider", return_value=True):
        result = asyncio.run(analyze_media(str(txt_path)))
    assert result == "Summary of text."

    # Verify call structure for text
    mock_completion.assert_called_once()
    call_args = mock_completion.call_args[1]
    assert "File Content:\n```\nHello\n```" in str(call_args["messages"][0]["content"])


def test_analyze_media_unsupported_type(mock_settings, tmp_path):
    """Test unsupported file type."""
    settings.download_dir = str(tmp_path)

    bin_path = tmp_path / "test.bin"
    bin_path.write_bytes(b"\x00\x01")  # unknown binary

    with patch("wet_mcp.llm._has_llm_provider", return_value=True):
        result = asyncio.run(analyze_media(str(bin_path)))
    assert (
        "Error: Cannot determine file type" in result
        or "Unsupported media type" in result
    )


@patch("wet_mcp.llm.acompletion")
def test_analyze_media_large_text_file(mock_completion, mock_settings, tmp_path):
    """Test truncation of large text files."""
    settings.download_dir = str(tmp_path)

    txt_path = tmp_path / "large.txt"
    # Create content larger than 100,000 chars
    large_content = "a" * 100005
    txt_path.write_text(large_content)

    # Mock response
    mock_response = MagicMock()
    mock_response.choices[0].message.content = "Summary of large text."
    mock_completion.return_value = mock_response

    with patch("wet_mcp.llm._has_llm_provider", return_value=True):
        result = asyncio.run(analyze_media(str(txt_path)))
    assert result == "Summary of large text."

    # Verify truncation
    mock_completion.assert_called_once()
    call_args = mock_completion.call_args[1]
    sent_content = call_args["messages"][0]["content"]

    # Expected truncated content
    expected_body = "a" * 100000 + "\n...[truncated]"

    assert expected_body in sent_content
    assert "a" * 100001 not in sent_content


def test_analyze_media_path_traversal(mock_settings, tmp_path):
    """Test that analyze_media blocks files outside download_dir."""
    settings.download_dir = str(tmp_path / "downloads")

    # Try to access a file outside download_dir
    outside_file = tmp_path / "secret.txt"
    outside_file.write_text("secret data")

    with patch("wet_mcp.llm._has_llm_provider", return_value=True):
        result = asyncio.run(analyze_media(str(outside_file)))
    assert "Error: Access denied" in result
    assert "download directory" in result


async def test_encode_image_valid(tmp_path):
    """Test encode_image with a valid image file."""

    img_path = tmp_path / "test.png"
    img_path.write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00")
    result = await encode_image(str(img_path))
    # base64 of above bytes
    import base64

    expected = base64.b64encode(b"\x89PNG\r\n\x1a\n\x00\x00").decode("utf-8")
    assert result == expected


async def test_encode_image_not_found(tmp_path):
    """Test encode_image with a non-existent file raises FileNotFoundError."""

    with pytest.raises(FileNotFoundError):
        await encode_image(str(tmp_path / "nonexistent.png"))


async def test_encode_image_empty(tmp_path):
    """Test encode_image with an empty file."""

    img_path = tmp_path / "empty.png"
    img_path.write_bytes(b"")
    result = await encode_image(str(img_path))
    assert result == ""


async def test_read_and_truncate(tmp_path):
    """Test _read_and_truncate reads and truncates properly."""

    # Test small file
    txt_path = tmp_path / "small.txt"
    txt_path.write_text("hello", encoding="utf-8")
    assert await _read_and_truncate(str(txt_path)) == "hello"

    # Test large file
    txt_path = tmp_path / "large.txt"
    large_content = "a" * 100005
    txt_path.write_text(large_content, encoding="utf-8")
    result = await _read_and_truncate(str(txt_path))
    assert len(result) == 100000 + len("\n...[truncated]")
    assert result.endswith("\n...[truncated]")


def test_analyze_media_path_traversal_dotdot(mock_settings, tmp_path):
    """Test that path traversal via .. is blocked."""
    download_dir = tmp_path / "downloads"
    download_dir.mkdir()
    settings.download_dir = str(download_dir)

    # Create a file outside download_dir and reference it with ..
    outside_file = tmp_path / "secret.txt"
    outside_file.write_text("secret data")
    traversal_path = str(download_dir / ".." / "secret.txt")

    with patch("wet_mcp.llm._has_llm_provider", return_value=True):
        result = asyncio.run(analyze_media(traversal_path))
    assert "Error: Access denied" in result


def test_analyze_media_tilde_download_dir(mock_settings, tmp_path, monkeypatch):
    """Test that tilde (~) in download_dir is expanded correctly."""
    # Simulate download_dir with tilde like the default "~/.wet-mcp/downloads"
    fake_home = tmp_path / "fakehome"
    fake_home.mkdir()
    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.setenv("USERPROFILE", str(fake_home))  # Windows compat

    dl_dir = fake_home / ".wet-mcp" / "downloads"
    dl_dir.mkdir(parents=True)
    settings.download_dir = "~/.wet-mcp/downloads"

    # Create a valid file inside the tilde-expanded download dir
    img_file = dl_dir / "test.jpg"
    img_file.write_bytes(b"fake-image-data")

    with patch("wet_mcp.llm._has_llm_provider", return_value=True):
        # Should NOT get "Access denied" -- tilde must be expanded
        result = asyncio.run(analyze_media(str(img_file), "Describe"))
    # File exists and is within download_dir, so we should get past the path check
    # (will fail at LLM call since we didn't mock it, but NOT "Access denied")
    assert "Access denied" not in result


def test_get_model_capabilities_comprehensive():
    """Test all hardcoded models for vision and audio input."""
    for model in _VISION_MODELS:
        caps = get_model_capabilities(f"provider/{model}")
        assert caps["vision"] is True, f"Model {model} should have vision"

    for model in _AUDIO_INPUT_MODELS:
        caps = get_model_capabilities(model)
        assert caps["audio_input"] is True, f"Model {model} should have audio input"


def test_get_model_capabilities_audio_output():
    """Test audio output capability (mocking the currently empty set)."""
    with patch("wet_mcp.llm._AUDIO_OUTPUT_MODELS", {"test-audio-model"}):
        caps = get_model_capabilities("test-audio-model")
        assert caps["audio_output"] is True

        caps = get_model_capabilities("other-model")
        assert caps["audio_output"] is False


def test_get_model_capabilities_edge_cases():
    """Test edge cases for model naming."""
    # Multiple slashes - should take everything after the first slash
    assert get_model_capabilities("provider/part1/part2")["vision"] is False

    # Empty string
    caps = get_model_capabilities("")
    assert not any(caps.values())

    # Whitespace
    caps = get_model_capabilities("  gemini-2.5-flash  ")
    assert not any(caps.values())


def test_get_model_capabilities_legacy():
    """Test capability detection with hardcoded maps (legacy cases)."""
    # Vision + audio model
    caps = get_model_capabilities("gemini/gemini-3-flash-preview")
    assert caps == {
        "vision": True,
        "audio_input": True,
        "audio_output": False,
    }

    # Vision-only model (xAI)
    caps = get_model_capabilities("xai/grok-4-1-fast-reasoning")
    assert caps == {
        "vision": True,
        "audio_input": False,
        "audio_output": False,
    }

    # Unknown model
    caps = get_model_capabilities("some/unknown-model")
    assert caps == {
        "vision": False,
        "audio_input": False,
        "audio_output": False,
    }


def test_strip_provider():
    """Test provider prefix stripping."""
    assert _strip_provider("gemini/gemini-3-flash-preview") == "gemini-3-flash-preview"
    assert _strip_provider("openai/gpt-4") == "gpt-4"
    assert _strip_provider("bare-model") == "bare-model"
    assert _strip_provider("a/b/c") == "b/c"
    assert _strip_provider("/b") == "b"
    assert _strip_provider("b/") == ""
    assert _strip_provider("/") == ""


def test_detect_provider():
    """Test provider detection from model name."""

    assert _detect_provider("gemini/gemini-3-flash-preview") == "gemini"
    assert _detect_provider("openai/gpt-4") == "openai"
    assert _detect_provider("xai/grok-4-1-fast-reasoning") == "xai"
    assert _detect_provider("grok/some-model") == "xai"


def test_has_llm_provider():
    """Test LLM provider detection."""

    with patch.dict(os.environ, {}, clear=True):
        assert _has_llm_provider() is False

    with patch.dict(os.environ, {"GEMINI_API_KEY": "test"}, clear=True):
        assert _has_llm_provider() is True

    with patch.dict(os.environ, {"XAI_API_KEY": "test"}, clear=True):
        assert _has_llm_provider() is True


@pytest.mark.asyncio
async def test_acompletion_fallback_skips_error():
    """Test that acompletion skips failed fallbacks and continues to the next one."""

    # We mock _gemini_completion to fail (triggering fallback)
    # We mock _openai_completion to fail on first call and succeed on second call

    with (
        patch(
            "wet_mcp.llm._gemini_completion", side_effect=Exception("Primary failed")
        ),
        patch("wet_mcp.llm._openai_completion") as mock_openai,
    ):
        # Mocking the side effect to fail then succeed
        mock_response = MagicMock()
        mock_response.choices[0].message.content = "Fallback success"
        mock_openai.side_effect = [Exception("First fallback failed"), mock_response]

        result = await acompletion(
            model="gemini/primary",
            messages=[{"role": "user", "content": "hi"}],
            fallbacks=["openai/fail", "openai/success"],
        )

        assert result.choices[0].message.content == "Fallback success"
        assert mock_openai.call_count == 2


@pytest.mark.asyncio
async def test_acompletion_all_fallbacks_fail():
    """Test that acompletion raises the original exception if all fallbacks fail."""

    primary_error = Exception("Primary failed")

    with (
        patch("wet_mcp.llm._gemini_completion", side_effect=primary_error),
        patch(
            "wet_mcp.llm._openai_completion", side_effect=Exception("Fallback failed")
        ),
    ):
        with pytest.raises(Exception) as excinfo:
            await acompletion(
                model="gemini/primary",
                messages=[{"role": "user", "content": "hi"}],
                fallbacks=["openai/fail1", "openai/fail2"],
            )

        assert excinfo.value is primary_error
