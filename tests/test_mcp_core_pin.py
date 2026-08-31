"""Guard: wet-mcp must depend on the stable mcp-core storage and LLM APIs."""

import re
import tomllib
from pathlib import Path


def test_mcp_core_pin_is_exact_stable_1_23_2():
    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    deps = pyproject["project"]["dependencies"]
    core = next(d for d in deps if d.startswith("n24q02m-mcp-core"))

    match = re.fullmatch(r"n24q02m-mcp-core\[llm\]==([0-9][0-9A-Za-z.\-]*)", core)
    assert match, f"must use exact stable pin: {core}"
    assert match.group(1) == "1.23.2", f"wrong mcp-core version: {core}"


def test_no_uv_path_source_for_mcp_core():
    raw = Path("pyproject.toml").read_text(encoding="utf-8")
    if "[tool.uv.sources]" in raw:
        block = raw.split("[tool.uv.sources]", 1)[1]
        assert "mcp-core" not in block.lower(), "must use PyPI dep, not a path source"
