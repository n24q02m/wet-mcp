import os
import pytest
from wet_mcp.config import Settings

def test_setup_api_keys_sets_env_vars(monkeypatch):
    """Test that setup_api_keys parses the string and sets environment variables."""
    # Ensure environment is clean for this test
    monkeypatch.delenv("TEST_KEY_1", raising=False)
    monkeypatch.delenv("TEST_KEY_2", raising=False)

    # Create settings with a sample api_keys string
    settings = Settings(api_keys="TEST_KEY_1:val1,TEST_KEY_2:val2")

    # Call setup_api_keys
    keys_by_env = settings.setup_api_keys()

    # Check return value
    assert keys_by_env == {
        "TEST_KEY_1": ["val1"],
        "TEST_KEY_2": ["val2"],
    }

    # Check environment variables were set
    assert os.environ.get("TEST_KEY_1") == "val1"
    assert os.environ.get("TEST_KEY_2") == "val2"

def test_setup_api_keys_handles_empty():
    """Test setup_api_keys with empty input."""
    settings = Settings(api_keys="")
    assert settings.setup_api_keys() == {}

def test_setup_api_keys_handles_multiple_keys_for_same_env(monkeypatch):
    """Test setup_api_keys with multiple keys for the same environment variable."""
    # Ensure environment is clean for this test
    monkeypatch.delenv("MULTI_KEY", raising=False)

    settings = Settings(api_keys="MULTI_KEY:k1,MULTI_KEY:k2")

    keys_by_env = settings.setup_api_keys()

    assert keys_by_env == {
        "MULTI_KEY": ["k1", "k2"]
    }

    # Should set the first key
    assert os.environ.get("MULTI_KEY") == "k1"
