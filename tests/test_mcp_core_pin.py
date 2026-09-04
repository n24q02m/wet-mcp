"""Guard the mcp-core OAuth rotation contract consumed by wet-mcp."""

from pathlib import Path

import jwt
import pytest
from mcp_core.auth.local_oauth_app import create_local_oauth_app


def test_mcp_core_rotates_jwts_without_changing_the_vault_key(monkeypatch):
    monkeypatch.setenv("CREDENTIAL_SECRET", "unchanged-vault-key")
    monkeypatch.setenv("MCP_JWT_SIGNING_SECRET", "jwt-signing-key-a")
    _old_app, old_issuer = create_local_oauth_app(
        server_name="wet-mcp", relay_schema={"fields": []}
    )
    old_token = old_issuer.issue_access_token(sub="existing-sub")

    monkeypatch.setenv("MCP_JWT_SIGNING_SECRET", "jwt-signing-key-b")
    _new_app, new_issuer = create_local_oauth_app(
        server_name="wet-mcp", relay_schema={"fields": []}
    )

    with pytest.raises(jwt.InvalidSignatureError):
        new_issuer.verify_access_token(old_token)


def test_no_uv_path_source_for_mcp_core():
    raw = Path("pyproject.toml").read_text(encoding="utf-8")
    if "[tool.uv.sources]" in raw:
        block = raw.split("[tool.uv.sources]", 1)[1]
        assert "mcp-core" not in block.lower(), "must use PyPI dep, not a path source"
