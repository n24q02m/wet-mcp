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


def test_analyze_media_no_keys(tmp_path):
    """Test analyze_media without keys."""
    # Temporarily clear keys
    original_keys = settings.api_keys
    settings.api_keys = None
    settings.download_dir = str(tmp_path)

    img_path = tmp_path / "test.jpg"
    img_path.touch()

    result = asyncio.run(analyze_media(str(img_path)))

    settings.api_keys = original_keys
    assert "Error: LLM analysis requires LITELLM_PROXY_URL or API_KEYS" in result


def test_analyze_media_file_not_found(mock_settings, tmp_path):
    """Test file not found error."""
    settings.download_dir = str(tmp_path)
    result = asyncio.run(analyze_media(str(tmp_path / "non_existent_file.jpg")))
    assert "Error: File not found" in result


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

    result = asyncio.run(analyze_media(str(outside_file)))
    assert "Error: Access denied" in result
    assert "download directory" in result


def test_encode_image_valid(tmp_path):
    """Test encode_image with a valid image file."""
    from wet_mcp.llm import encode_image

    img_path = tmp_path / "test.png"
    img_path.write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00")
    result = encode_image(str(img_path))
    # base64 of above bytes
    import base64

    expected = base64.b64encode(b"\x89PNG\r\n\x1a\n\x00\x00").decode("utf-8")
    assert result == expected


def test_encode_image_not_found(tmp_path):
    """Test encode_image with a non-existent file raises FileNotFoundError."""
    from wet_mcp.llm import encode_image

    with pytest.raises(FileNotFoundError):
        encode_image(str(tmp_path / "nonexistent.png"))


def test_encode_image_empty(tmp_path):
    """Test encode_image with an empty file."""
    from wet_mcp.llm import encode_image

    img_path = tmp_path / "empty.png"
    img_path.write_bytes(b"")
    result = encode_image(str(img_path))
    assert result == ""


def test_encode_image_jpeg(tmp_path):
    """Test encode_image with a JPEG image file."""
    from wet_mcp.llm import encode_image

    img_path = tmp_path / "test.jpeg"
    img_path.write_bytes(b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01")
    result = encode_image(str(img_path))

    import base64

    expected = base64.b64encode(b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01").decode("utf-8")
    assert result == expected


def test_encode_image_permission_error(tmp_path, monkeypatch):
    """Test encode_image when open raises PermissionError."""
    import builtins

    import pytest

    from wet_mcp.llm import encode_image

    img_path = tmp_path / "noperm.png"
    img_path.write_bytes(b"data")

    # Mock open to raise PermissionError
    original_open = builtins.open

    def mock_open(*args, **kwargs):
        if args[0] == str(img_path):
            raise PermissionError("Permission denied")
        return original_open(*args, **kwargs)

    monkeypatch.setattr(builtins, "open", mock_open)

    with pytest.raises(PermissionError):
        encode_image(str(img_path))


def test_read_and_truncate(tmp_path):
    """Test _read_and_truncate reads and truncates properly."""
    from wet_mcp.llm import _read_and_truncate

    # Test small file
    txt_path = tmp_path / "small.txt"
    txt_path.write_text("hello", encoding="utf-8")
    assert _read_and_truncate(str(txt_path)) == "hello"

    # Test large file
    txt_path = tmp_path / "large.txt"
    large_content = "a" * 100005
    txt_path.write_text(large_content, encoding="utf-8")
    result = _read_and_truncate(str(txt_path))
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

    result = asyncio.run(analyze_media(traversal_path))
    assert "Error: Access denied" in result


def test_analyze_media_tilde_download_dir(mock_settings, tmp_path, monkeypatch):
    """Test that tilde (~) in download_dir is expanded correctly."""
    # Simulate download_dir with tilde like the default "~/.wet-mcp/downloads"
    fake_home = tmp_path / "fakehome"
    fake_home.mkdir()
    monkeypatch.setenv("HOME", str(fake_home))

    dl_dir = fake_home / ".wet-mcp" / "downloads"
    dl_dir.mkdir(parents=True)
    settings.download_dir = "~/.wet-mcp/downloads"

    # Create a valid file inside the tilde-expanded download dir
    img_file = dl_dir / "test.jpg"
    img_file.write_bytes(b"fake-image-data")

    # Should NOT get "Access denied" — tilde must be expanded
    result = asyncio.run(analyze_media(str(img_file), "Describe"))
    # File exists and is within download_dir, so we should get past the path check
    # (will fail at LLM call since we didn't mock it, but NOT "Access denied")
    assert "Access denied" not in result


@patch("litellm.supports_vision")
@patch("litellm.supports_audio_input")
@patch("litellm.supports_audio_output")
def test_get_model_capabilities(mock_audio_out, mock_audio_in, mock_vision):
    from wet_mcp.llm import get_model_capabilities

    mock_vision.return_value = True
    mock_audio_in.return_value = False
    mock_audio_out.return_value = True

    caps = get_model_capabilities("test-model")

    mock_vision.assert_called_once_with("test-model")
    mock_audio_in.assert_called_once_with("test-model")
    mock_audio_out.assert_called_once_with("test-model")

    assert caps == {
        "vision": True,
        "audio_input": False,
        "audio_output": True,
    }


@patch("litellm.supports_vision")
@patch("litellm.supports_audio_input")
@patch("litellm.supports_audio_output")
def test_get_model_capabilities_exception(mock_audio_out, mock_audio_in, mock_vision):
    from wet_mcp.llm import get_model_capabilities

    mock_vision.side_effect = Exception("LiteLLM Error")

    with pytest.raises(Exception, match="LiteLLM Error"):
        get_model_capabilities("test-model")

    mock_vision.assert_called_once_with("test-model")
    mock_audio_in.assert_not_called()
    mock_audio_out.assert_not_called()
