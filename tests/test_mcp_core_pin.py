"""Guard: wet-mcp must depend on a mcp-core release that ships the storage
backends (CredentialBackend / CfKvBackend) AND the PerPluginStore token sub-key.
"""

import tomllib
from pathlib import Path


def test_mcp_core_pin_includes_token_subkey():
    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    deps = pyproject["project"]["dependencies"]
    core = next(d for d in deps if d.startswith("n24q02m-mcp-core"))
    # Storage backends shipped in 1.18.0b4; the token sub-key in 1.18.0b5.
    assert "1.18.0b5" in core, f"expected >=1.18.0b5 floor, got: {core}"


def test_no_uv_path_source_for_mcp_core():
    raw = Path("pyproject.toml").read_text(encoding="utf-8")
    if "[tool.uv.sources]" in raw:
        block = raw.split("[tool.uv.sources]", 1)[1]
        assert "mcp-core" not in block.lower(), "must use PyPI dep, not a path source"
