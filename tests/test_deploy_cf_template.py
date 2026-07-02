"""Tests for the CI CF-deploy template rendering in ``scripts/deploy_cf.py``.

``deploy_cf.py --from-template`` reconstructs the gitignored
``wrangler.deploy.jsonc`` from the committed placeholder template + env (CI
provides the real IDs as GitHub Actions secrets). These tests exercise the pure
``render_template`` substitution without touching docker/wrangler.
"""

from __future__ import annotations

import importlib.util
import json
import pathlib

import pytest

_SCRIPT = pathlib.Path(__file__).resolve().parent.parent / "scripts" / "deploy_cf.py"
_spec = importlib.util.spec_from_file_location("deploy_cf", _SCRIPT)
assert _spec is not None and _spec.loader is not None
deploy_cf = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(deploy_cf)


def test_render_template_substitutes_env(tmp_path, monkeypatch):
    tpl = tmp_path / "wrangler.deploy.template.jsonc"
    tpl.write_text(
        '{"image":"registry.cloudflare.com/${CLOUDFLARE_ACCOUNT_ID}/wet-mcp:${IMAGE_TAG}",'
        '"vars":{"PUBLIC_URL":"${PUBLIC_URL}"}}',
        encoding="utf-8",
    )
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "acct123")
    monkeypatch.setenv("IMAGE_TAG", "v9.9.9")
    # A non-URL sentinel: this unit test exercises substitution mechanics, and a
    # real URL literal would trip CodeQL's url-substring-sanitization heuristic.
    # Parse + equality-assert the rendered JSON (not substring) so the test is
    # precise and CodeQL sees no url-in-string validation pattern.
    monkeypatch.setenv("PUBLIC_URL", "PUBLIC-URL-SENTINEL")
    cfg = json.loads(deploy_cf.render_template(str(tpl)))
    assert cfg["image"] == "registry.cloudflare.com/acct123/wet-mcp:v9.9.9"
    assert cfg["vars"]["PUBLIC_URL"] == "PUBLIC-URL-SENTINEL"


def test_render_template_missing_var_fails_loudly(tmp_path, monkeypatch):
    tpl = tmp_path / "t.jsonc"
    tpl.write_text('{"x":"${DEFINITELY_MISSING_VAR}"}', encoding="utf-8")
    monkeypatch.delenv("DEFINITELY_MISSING_VAR", raising=False)
    with pytest.raises(SystemExit):
        deploy_cf.render_template(str(tpl))


def test_committed_template_renders_to_valid_json(monkeypatch):
    """The real committed template must render cleanly when all documented CI
    env vars are set, and parse as valid JSON (catches a ${VAR} typo or a stray
    placeholder the tiny unit example would miss)."""
    for k, v in {
        "CLOUDFLARE_ACCOUNT_ID": "acct",
        "IMAGE_TAG": "v1",
        "CF_KV_ID": "kvid",
        "CF_D1_ID": "d1id",
        "CF_VECTORIZE_ID": "vecidx",
        "PUBLIC_URL": "https://wet.n24q02m.com",
    }.items():
        monkeypatch.setenv(k, v)
    tpl = _SCRIPT.parent.parent / "wrangler.deploy.template.jsonc"
    out = deploy_cf.render_template(str(tpl))
    assert "${" not in out  # no leftover placeholder
    cfg = json.loads(deploy_cf._strip_jsonc(out))
    assert cfg["name"] == "wet-mcp-worker"
    assert cfg["containers"][0]["image"] == "registry.cloudflare.com/acct/wet-mcp:v1"
    assert cfg["kv_namespaces"][0]["id"] == "kvid"
    assert cfg["d1_databases"][0]["database_id"] == "d1id"
    assert cfg["vars"]["PUBLIC_URL"] == "https://wet.n24q02m.com"
