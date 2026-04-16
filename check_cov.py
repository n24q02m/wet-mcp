import sys
import os
import coverage
from unittest.mock import patch, MagicMock

# Force clean state for the module if it was already imported
if "wet_mcp.credential_state" in sys.modules:
    del sys.modules["wet_mcp.credential_state"]

# Mock dependencies to avoid Pydantic/other issues
sys.modules["mcp"] = MagicMock()
sys.modules["mcp.server"] = MagicMock()
sys.modules["mcp.server.fastmcp"] = MagicMock()
sys.modules["mcp.types"] = MagicMock()

cov = coverage.Coverage(include="src/wet_mcp/credential_state.py")
cov.start()

from wet_mcp.credential_state import resolve_credential_state, CredentialState, CLOUD_KEYS

def run_tests():
    print("Running tests...")
    # 1. Env vars
    with patch.dict(os.environ, {"GEMINI_API_KEY": "test"}):
        print("Test 1: Env vars")
        resolve_credential_state()

    # 2. Config file success
    with patch.dict(os.environ, {k: "" for k in CLOUD_KEYS}):
        with patch("mcp_core.storage.config_file.read_config", return_value={"GEMINI_API_KEY": "test"}):
            with patch("mcp_core.get_mode", return_value=None):
                print("Test 2: Config file success")
                resolve_credential_state()

    # 3. Config file read error
    with patch.dict(os.environ, {k: "" for k in CLOUD_KEYS}):
        with patch("mcp_core.storage.config_file.read_config", side_effect=Exception("BOOM")):
             with patch("mcp_core.get_mode", return_value=None):
                print("Test 3: Config file read error")
                resolve_credential_state()

    # 4. Local mode
    with patch.dict(os.environ, {k: "" for k in CLOUD_KEYS}):
        with patch("mcp_core.storage.config_file.read_config", return_value=None):
            with patch("mcp_core.get_mode", return_value="local"):
                print("Test 4: Local mode")
                resolve_credential_state()

    # 5. Local mode error
    with patch.dict(os.environ, {k: "" for k in CLOUD_KEYS}):
        with patch("mcp_core.storage.config_file.read_config", return_value=None):
            with patch("mcp_core.get_mode", side_effect=Exception("BOOM")):
                print("Test 5: Local mode error")
                resolve_credential_state()

run_tests()

cov.stop()
cov.save()
cov.report(show_missing=True)
