import sys
from unittest import mock

import pytest
from wet_mcp.config import _detect_gpu, _has_gguf_support, _resolve_local_model


def test_detect_gpu_cuda():
    """Test _detect_gpu returns True if CUDAExecutionProvider is available."""
    mock_ort = mock.MagicMock()
    mock_ort.get_available_providers.return_value = ["CUDAExecutionProvider"]

    with mock.patch.dict(sys.modules, {"onnxruntime": mock_ort}):
        assert _detect_gpu() is True


def test_detect_gpu_dml():
    """Test _detect_gpu returns True if DmlExecutionProvider is available."""
    mock_ort = mock.MagicMock()
    mock_ort.get_available_providers.return_value = ["DmlExecutionProvider"]

    with mock.patch.dict(sys.modules, {"onnxruntime": mock_ort}):
        assert _detect_gpu() is True


def test_detect_gpu_cpu_only():
    """Test _detect_gpu returns False if only CPUExecutionProvider is available."""
    mock_ort = mock.MagicMock()
    mock_ort.get_available_providers.return_value = ["CPUExecutionProvider"]

    with mock.patch.dict(sys.modules, {"onnxruntime": mock_ort}):
        assert _detect_gpu() is False


def test_detect_gpu_exception():
    """Test _detect_gpu returns False if onnxruntime raises Exception."""
    mock_ort = mock.MagicMock()
    mock_ort.get_available_providers.side_effect = Exception("Boom")

    with mock.patch.dict(sys.modules, {"onnxruntime": mock_ort}):
        assert _detect_gpu() is False


def test_detect_gpu_import_error():
    """Test _detect_gpu returns False if onnxruntime is not installed."""
    # We patch sys.modules to remove onnxruntime if present
    # And mock builtins.__import__ to raise ImportError for onnxruntime

    # However, since builtins.__import__ is tricky, we can just patch sys.modules
    # such that 'onnxruntime' is NOT in it, and rely on the fact that if it's not there,
    # python tries to find it. But we can't easily mock the loader to fail.

    # Easier: Just mock sys.modules['onnxruntime'] to be something that raises
    # ImportError on access? No.

    # If onnxruntime is in sys.modules, import uses it.
    # If not, import searches.

    # Let's try mocking builtins.__import__ properly.

    orig_import = __import__

    def side_effect(name, *args, **kwargs):
        if name == 'onnxruntime':
            raise ImportError("No module named 'onnxruntime'")
        return orig_import(name, *args, **kwargs)

    with mock.patch('builtins.__import__', side_effect=side_effect):
        # Temporarily remove from sys.modules to force import attempt
        with mock.patch.dict(sys.modules):
            if 'onnxruntime' in sys.modules:
                del sys.modules['onnxruntime']
            assert _detect_gpu() is False


def test_has_gguf_support_installed():
    """Test _has_gguf_support returns True if llama_cpp is importable."""
    with mock.patch.dict(sys.modules, {"llama_cpp": mock.MagicMock()}):
        assert _has_gguf_support() is True


def test_has_gguf_support_not_installed():
    """Test _has_gguf_support returns False if llama_cpp is not importable."""
    orig_import = __import__

    def side_effect(name, *args, **kwargs):
        if name == 'llama_cpp':
            raise ImportError("No module named 'llama_cpp'")
        return orig_import(name, *args, **kwargs)

    with mock.patch('builtins.__import__', side_effect=side_effect):
        with mock.patch.dict(sys.modules):
            if 'llama_cpp' in sys.modules:
                del sys.modules['llama_cpp']
            assert _has_gguf_support() is False


def test_resolve_local_model_gpu_gguf():
    """Test _resolve_local_model chooses GGUF if GPU and GGUF support are present."""
    with mock.patch("wet_mcp.config._detect_gpu", return_value=True), \
         mock.patch("wet_mcp.config._has_gguf_support", return_value=True):
        assert _resolve_local_model("onnx", "gguf") == "gguf"


def test_resolve_local_model_gpu_no_gguf():
    """Test _resolve_local_model chooses ONNX if GPU present but no GGUF support."""
    with mock.patch("wet_mcp.config._detect_gpu", return_value=True), \
         mock.patch("wet_mcp.config._has_gguf_support", return_value=False):
        assert _resolve_local_model("onnx", "gguf") == "onnx"


def test_resolve_local_model_no_gpu_gguf():
    """Test _resolve_local_model chooses ONNX if no GPU, even with GGUF support."""
    with mock.patch("wet_mcp.config._detect_gpu", return_value=False), \
         mock.patch("wet_mcp.config._has_gguf_support", return_value=True):
        assert _resolve_local_model("onnx", "gguf") == "onnx"


def test_resolve_local_model_no_gpu_no_gguf():
    """Test _resolve_local_model chooses ONNX if neither GPU nor GGUF support."""
    with mock.patch("wet_mcp.config._detect_gpu", return_value=False), \
         mock.patch("wet_mcp.config._has_gguf_support", return_value=False):
        assert _resolve_local_model("onnx", "gguf") == "onnx"
