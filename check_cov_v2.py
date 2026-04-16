import sys
import os
import coverage
from unittest.mock import patch, MagicMock

# Force clean state for the module
if "wet_mcp.credential_state" in sys.modules:
    del sys.modules["wet_mcp.credential_state"]

# Mock dependencies to avoid Pydantic/other issues
sys.modules["mcp"] = MagicMock()
sys.modules["mcp.server"] = MagicMock()
sys.modules["mcp.server.fastmcp"] = MagicMock()
sys.modules["mcp.types"] = MagicMock()

cov = coverage.Coverage(source=["src/wet_mcp/credential_state.py"])
cov.start()

from wet_mcp.credential_state import resolve_credential_state, CredentialState, CLOUD_KEYS

# 3. Config file read error (as in test_config_file_read_error)
with patch.dict(os.environ, {k: "" for k in CLOUD_KEYS}):
    with patch("mcp_core.storage.config_file.read_config", side_effect=Exception("BOOM")):
            with patch("mcp_core.get_mode", return_value=None):
                print("Test: Config file read error")
                resolve_credential_state()

cov.stop()
cov.save()

# Find lines 89-90
data = cov.get_data()
lines = data.lines(os.path.abspath("src/wet_mcp/credential_state.py"))
print(f"Lines hit in 85-95 range: {[l for l in lines if 85 <= l <= 95]}")

cov.report(show_missing=True)
