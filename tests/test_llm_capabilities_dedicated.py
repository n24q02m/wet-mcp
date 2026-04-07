from unittest.mock import patch, MagicMock
import pytest
import sys
import importlib.util

# This test file is designed to be runnable via standard pytest but uses
# lazy loading and manual mocking to bypass the heavy dependency tree of wet_mcp.

def import_llm():
    """Helper to import wet_mcp.llm while mocking its heavy dependencies."""
    mock_modules = [
        "loguru", "mcp", "mcp.server", "mcp.server.fastmcp", "mcp.types",
        "pydantic", "pydantic_settings", "wet_mcp.config", "google", "openai",
        "cohere", "qwen3_embed", "diskcache", "cryptography", "markitdown",
        "aiolimiter", "mcp_relay_core", "n24q02m_web_core",
        "n24q02m_web_core.search", "n24q02m_web_core.search.runner", "crawl4ai",
        "httpx", "pillow", "PIL", "PIL.Image", "google.genai", "google.auth",
        "googleapiclient", "googleapiclient.discovery", "googleapiclient.http",
        "web_core", "web_core.http", "web_core.http.client", "web_core.http.url",
        "web_core.search", "web_core.search.runner", "web_core.search.client"
    ]
    for mod in mock_modules:
        if mod not in sys.modules:
            m = MagicMock()
            if "." in mod:
                m.__path__ = []
            sys.modules[mod] = m

    # Mock importlib.metadata.version to avoid PackageNotFoundError
    import importlib.metadata
    if "wet_mcp_version_mock" not in sys.modules:
        original_version = importlib.metadata.version
        def mock_version(package):
            if package == "wet-mcp":
                return "2.24.0"
            return original_version(package)
        sys.modules["wet_mcp_version_mock"] = patch("importlib.metadata.version", side_effect=mock_version)
        sys.modules["wet_mcp_version_mock"].start()

    # Load the module
    if "wet_mcp.llm" not in sys.modules:
        spec = importlib.util.spec_from_file_location("wet_mcp.llm", "src/wet_mcp/llm.py")
        module = importlib.util.module_from_spec(spec)
        sys.modules["wet_mcp.llm"] = module
        spec.loader.exec_module(module)

    return sys.modules["wet_mcp.llm"]

def test_get_model_capabilities_comprehensive():
    """Test get_model_capabilities with various model types and prefixes."""
    llm = import_llm()
    get_model_capabilities = llm.get_model_capabilities

    # 1. Test a model with both vision and audio input (Gemini)
    caps = get_model_capabilities("gemini/gemini-3-flash-preview")
    assert caps["vision"] is True
    assert caps["audio_input"] is True
    assert caps["audio_output"] is False

    # 2. Test a vision-only model (Grok)
    caps = get_model_capabilities("xai/grok-4-1-fast-reasoning")
    assert caps["vision"] is True
    assert caps["audio_input"] is False
    assert caps["audio_output"] is False

    # 3. Test a bare model name (no provider prefix)
    caps = get_model_capabilities("gemini-2.5-pro")
    assert caps["vision"] is True
    assert caps["audio_input"] is True

    # 4. Test an unknown model
    caps = get_model_capabilities("openai/gpt-4o-unknown")
    assert caps["vision"] is False
    assert caps["audio_input"] is False
    assert caps["audio_output"] is False

def test_get_model_capabilities_audio_output_logic():
    """Verify audio_output logic by mocking _AUDIO_OUTPUT_MODELS."""
    llm = import_llm()
    get_model_capabilities = llm.get_model_capabilities

    # Since _AUDIO_OUTPUT_MODELS is currently empty, we mock it to test the logic
    # We use direct modification because patch might have issues with how we're importing
    original = llm._AUDIO_OUTPUT_MODELS
    llm._AUDIO_OUTPUT_MODELS = {"audio-model"}
    try:
        caps = get_model_capabilities("provider/audio-model")
        assert caps["audio_output"] is True

        caps = get_model_capabilities("provider/other-model")
        assert caps["audio_output"] is False
    finally:
        llm._AUDIO_OUTPUT_MODELS = original

def test_strip_provider_edge_cases():
    """Test _strip_provider with various inputs."""
    llm = import_llm()
    _strip_provider = llm._strip_provider

    assert _strip_provider("provider/model") == "model"
    assert _strip_provider("model-only") == "model-only"
    assert _strip_provider("multiple/slashes/model") == "slashes/model"
    assert _strip_provider("") == ""

def test_get_model_capabilities_empty_input():
    """Test with empty string as model name."""
    llm = import_llm()
    get_model_capabilities = llm.get_model_capabilities
    caps = get_model_capabilities("")
    assert caps == {"vision": False, "audio_input": False, "audio_output": False}
