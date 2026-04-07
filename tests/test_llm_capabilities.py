from wet_mcp.llm import (
    _AUDIO_INPUT_MODELS,
    _AUDIO_OUTPUT_MODELS,
    _VISION_MODELS,
    get_model_capabilities,
)


def test_get_model_capabilities_comprehensive():
    """Comprehensive test for model capabilities across all known models."""

    # Test all vision models
    for model in _VISION_MODELS:
        caps = get_model_capabilities(model)
        assert caps["vision"] is True
        # Check if it also has audio_input (some do, some don't)
        assert caps["audio_input"] == (model in _AUDIO_INPUT_MODELS)
        assert caps["audio_output"] == (model in _AUDIO_OUTPUT_MODELS)

    # Test all audio input models
    for model in _AUDIO_INPUT_MODELS:
        caps = get_model_capabilities(model)
        assert caps["audio_input"] is True
        assert caps["vision"] == (model in _VISION_MODELS)
        assert caps["audio_output"] == (model in _AUDIO_OUTPUT_MODELS)

    # Test audio output models (currently empty, but good for future proofing)
    for model in _AUDIO_OUTPUT_MODELS:
        caps = get_model_capabilities(model)
        assert caps["audio_output"] is True


def test_get_model_capabilities_with_providers():
    """Test get_model_capabilities with different provider prefixes."""
    providers = ["gemini/", "google/", "openai/", "gpt/", "xai/", "grok/"]

    # Pick a model that has both vision and audio
    test_model = "gemini-3-flash-preview"
    assert test_model in _VISION_MODELS
    assert test_model in _AUDIO_INPUT_MODELS

    for provider in providers:
        full_name = f"{provider}{test_model}"
        caps = get_model_capabilities(full_name)
        assert caps["vision"] is True
        assert caps["audio_input"] is True
        assert caps["audio_output"] is False


def test_get_model_capabilities_non_existent():
    """Test get_model_capabilities with unknown models."""
    caps = get_model_capabilities("unknown-provider/unknown-model")
    assert caps == {
        "vision": False,
        "audio_input": False,
        "audio_output": False,
    }

    caps = get_model_capabilities("just-a-random-string")
    assert caps == {
        "vision": False,
        "audio_input": False,
        "audio_output": False,
    }


def test_get_model_capabilities_empty_string():
    """Test get_model_capabilities with an empty string."""
    caps = get_model_capabilities("")
    assert caps == {
        "vision": False,
        "audio_input": False,
        "audio_output": False,
    }
