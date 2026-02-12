import os
from unittest import mock

from wet_mcp.config import Settings


def test_setup_api_keys_valid():
    """Test setup_api_keys with valid input."""
    settings = Settings(api_keys="GOOGLE_API_KEY:abc,OPENAI_API_KEY:xyz")

    with mock.patch.dict(os.environ, {}, clear=True):
        keys = settings.setup_api_keys()

        assert keys == {"GOOGLE_API_KEY": ["abc"], "OPENAI_API_KEY": ["xyz"]}

        assert os.environ["GOOGLE_API_KEY"] == "abc"
        assert os.environ["OPENAI_API_KEY"] == "xyz"


def test_setup_api_keys_empty():
    """Test setup_api_keys with empty input."""
    settings_none = Settings(api_keys=None)
    with mock.patch.dict(os.environ, {}, clear=True):
        assert settings_none.setup_api_keys() == {}
        assert len(os.environ) == 0

    settings_empty = Settings(api_keys="")
    with mock.patch.dict(os.environ, {}, clear=True):
        assert settings_empty.setup_api_keys() == {}
        assert len(os.environ) == 0


def test_setup_api_keys_invalid_format():
    """Test setup_api_keys with invalid format strings."""
    settings = Settings(api_keys="INVALID_KEY,VALID:key")

    with mock.patch.dict(os.environ, {}, clear=True):
        keys = settings.setup_api_keys()

        assert keys == {"VALID": ["key"]}
        assert os.environ.get("INVALID_KEY") is None
        assert os.environ["VALID"] == "key"

    settings = Settings(api_keys="ENV:,VALID:key")
    with mock.patch.dict(os.environ, {}, clear=True):
        keys = settings.setup_api_keys()
        assert keys == {"VALID": ["key"]}
        assert os.environ.get("ENV") is None


def test_setup_api_keys_multiple_keys():
    """Test setup_api_keys with multiple keys for same env var."""
    settings = Settings(api_keys="ENV:key1,ENV:key2")

    with mock.patch.dict(os.environ, {}, clear=True):
        keys = settings.setup_api_keys()

        assert keys == {"ENV": ["key1", "key2"]}

        assert os.environ["ENV"] == "key1"


def test_setup_api_keys_whitespace():
    """Test setup_api_keys with whitespace around keys."""
    settings = Settings(api_keys=" ENV : key1 , OTHER : key2 ")

    with mock.patch.dict(os.environ, {}, clear=True):
        keys = settings.setup_api_keys()

        assert keys == {"ENV": ["key1"], "OTHER": ["key2"]}
        assert os.environ["ENV"] == "key1"
        assert os.environ["OTHER"] == "key2"
