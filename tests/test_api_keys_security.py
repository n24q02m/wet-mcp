import os
import tempfile

import pytest

from wet_mcp.config import Settings


@pytest.fixture(autouse=True)
def clean_env():
    """Ensure clean environment for each test."""
    keys_to_clean = ["API_KEYS", "TEST_KEY", "ANOTHER_KEY", "FILE_KEY", "FILE_KEY_2", "LINE_KEY_1", "LINE_KEY_2"]
    original_env = {}
    for key in keys_to_clean:
        if key in os.environ:
            original_env[key] = os.environ[key]
            del os.environ[key]
    yield
    # Cleanup added keys
    for key in keys_to_clean:
        if key in os.environ:
            del os.environ[key]
    # Restore original env
    for key, val in original_env.items():
        os.environ[key] = val

def test_api_keys_direct():
    """Test standard API_KEYS environment variable."""
    os.environ["API_KEYS"] = "TEST_KEY:123,ANOTHER_KEY:456"
    settings = Settings()
    keys = settings.setup_api_keys()

    assert os.environ.get("TEST_KEY") == "123"
    assert os.environ.get("ANOTHER_KEY") == "456"
    assert keys["TEST_KEY"] == ["123"]

def test_api_keys_file_comma():
    """Test loading API_KEYS from a file (comma separated)."""
    with tempfile.NamedTemporaryFile(mode="w", delete=False) as f:
        f.write("FILE_KEY:abc,FILE_KEY_2:def")
        tmp_path = f.name

    try:
        os.environ["API_KEYS"] = f"@{tmp_path}"
        settings = Settings()
        keys = settings.setup_api_keys()

        assert os.environ.get("FILE_KEY") == "abc"
        assert os.environ.get("FILE_KEY_2") == "def"
        assert keys["FILE_KEY"] == ["abc"]
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)

def test_api_keys_file_newlines():
    """Test loading API_KEYS from a file (newline separated)."""
    with tempfile.NamedTemporaryFile(mode="w", delete=False) as f:
        f.write("LINE_KEY_1:xyz\nLINE_KEY_2:uvw")
        tmp_path = f.name

    try:
        os.environ["API_KEYS"] = f"@{tmp_path}"
        settings = Settings()
        keys = settings.setup_api_keys()

        assert os.environ.get("LINE_KEY_1") == "xyz"
        assert os.environ.get("LINE_KEY_2") == "uvw"
        assert keys["LINE_KEY_1"] == ["xyz"]
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
