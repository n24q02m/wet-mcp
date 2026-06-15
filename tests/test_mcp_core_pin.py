"""Guard: wet-mcp must depend on a mcp-core release that ships the storage
backends (CredentialBackend / CfKvBackend) AND the PerPluginStore token sub-key.
"""

import re
import tomllib
from pathlib import Path

from packaging.version import Version


def test_mcp_core_pin_includes_token_subkey():
    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    deps = pyproject["project"]["dependencies"]
    core = next(d for d in deps if d.startswith("n24q02m-mcp-core"))
    # Storage backends shipped in 1.18.0b4; the token sub-key in 1.18.0b5;
    # CfKvBackend.ready() readiness probe in 1.18.0b6. Compare the >= floor as a
    # version (not a brittle substring) so legitimate bumps past b5 still pass.
    m = re.search(r">=\s*([0-9][0-9A-Za-z.\-]*)", core)
    assert m, f"no >= floor in pin: {core}"
    assert Version(m.group(1)) >= Version("1.18.0b5"), f"floor too low: {core}"


def test_no_uv_path_source_for_mcp_core():
    raw = Path("pyproject.toml").read_text(encoding="utf-8")
    if "[tool.uv.sources]" in raw:
        block = raw.split("[tool.uv.sources]", 1)[1]
        assert "mcp-core" not in block.lower(), "must use PyPI dep, not a path source"
