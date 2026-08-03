"""Tests for the D1 migration step in ``scripts/deploy_cf.py``.

``wrangler deploy`` does NOT apply D1 migrations -- ``migrations_dir`` on the D1
binding only tells ``wrangler d1 migrations *`` where to look. Before this step
existed, no deploy path touched the remote schema, so prod D1 drifted from
``migrations/`` and a release shipping code that reads a new column failed at
runtime (issue #1617).

These tests pin the two properties that make the step correct:
  1. the migration command runs BEFORE ``wrangler deploy`` (schema before code);
  2. ``--dry-run`` prints the plan and executes nothing.
"""

from __future__ import annotations

import importlib.util
import json
import os
import pathlib
import shutil
import subprocess

import pytest

_SCRIPT = pathlib.Path(__file__).resolve().parent.parent / "scripts" / "deploy_cf.py"
_spec = importlib.util.spec_from_file_location("deploy_cf_migrations", _SCRIPT)
assert _spec is not None and _spec.loader is not None
deploy_cf = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(deploy_cf)


def _fake_cfg() -> dict:
    """Shape of the RENDERED wrangler.deploy.jsonc (real IDs), not the committed
    placeholder wrangler.jsonc."""
    return {
        "name": "wet-mcp-worker",
        # account segment must be hex: _image_parts() rejects anything else.
        "containers": [{"image": "registry.cloudflare.com/abc123/wet-mcp:oldtag"}],
        "d1_databases": [
            {
                "binding": "D1",
                "database_name": "wet-docs",
                "database_id": "d1id",
                "migrations_dir": "migrations",
            }
        ],
        "vars": {"PUBLIC_URL": "PUBLIC-URL-SENTINEL"},
    }


def _record_run(monkeypatch, cfg: dict) -> list[list[str]]:
    """Drive main() with every side effect stubbed, capturing the argv of each
    _run() call in order."""
    calls: list[list[str]] = []
    monkeypatch.setattr(deploy_cf, "_load_deploy_config", lambda repo: cfg)
    monkeypatch.setattr(deploy_cf, "_run", lambda cmd, **kw: calls.append(list(cmd)))
    monkeypatch.setattr(deploy_cf, "_wait_ready", lambda *a, **k: None)
    monkeypatch.setattr(deploy_cf, "_set_image_tag", lambda *a, **k: None)
    return calls


def _index_of(calls: list[list[str]], *needle: str) -> int:
    for i, cmd in enumerate(calls):
        if all(tok in cmd for tok in needle):
            return i
    raise AssertionError(f"no call containing {needle} in {calls}")


def test_migrations_apply_runs_before_wrangler_deploy(monkeypatch):
    """Schema first, then code. Deploying the worker before the columns exist
    leaves a live window where the new code 500s on a missing column."""
    calls = _record_run(monkeypatch, _fake_cfg())
    assert deploy_cf.main(["--skip-build", "--no-canary", "--tag", "t1"]) == 0
    assert _index_of(calls, "migrations", "apply") < _index_of(calls, "deploy")


def test_migrations_command_shape(monkeypatch):
    """--remote is what makes it hit prod D1 (the default is the local sim), and
    --config must be the rendered deploy config with the real database id."""
    calls = _record_run(monkeypatch, _fake_cfg())
    deploy_cf.main(["--skip-build", "--no-canary", "--tag", "t1"])
    cmd = calls[_index_of(calls, "migrations", "apply")]
    assert cmd == [
        "bunx",
        "wrangler",
        "d1",
        "migrations",
        "apply",
        "wet-docs",
        "--remote",
        "--config",
        deploy_cf.DEPLOY_CONFIG,
    ]


def test_no_d1_binding_emits_no_migration_call(monkeypatch):
    """A fork without a D1 binding must still deploy, not crash on a KeyError."""
    cfg = _fake_cfg()
    del cfg["d1_databases"]
    calls = _record_run(monkeypatch, cfg)
    assert deploy_cf.main(["--skip-build", "--no-canary", "--tag", "t1"]) == 0
    assert not any("migrations" in c for c in calls)
    _index_of(calls, "deploy")  # the deploy itself still happened


def test_dry_run_prints_migration_but_executes_nothing(monkeypatch, capsys):
    """--dry-run must reach the real _run() and still spawn no subprocess, so the
    printed plan is trustworthy without touching prod D1."""
    monkeypatch.setattr(deploy_cf, "_load_deploy_config", lambda repo: _fake_cfg())

    def _boom(*a, **k):
        raise AssertionError(f"--dry-run must not execute a subprocess: {a}")

    monkeypatch.setattr(deploy_cf.subprocess, "run", _boom)
    assert deploy_cf.main(["--dry-run", "--no-canary", "--tag", "t1"]) == 0
    out = capsys.readouterr().out
    assert "wrangler d1 migrations apply wet-docs --remote" in out
    assert out.index("d1 migrations apply") < out.index("wrangler deploy --config")


def test_committed_template_keeps_d1_migrations_wired(monkeypatch):
    """The step reads database_name from the rendered config; dropping it (or
    migrations_dir) would silently turn the migration into a no-op."""
    for k, v in {
        "CLOUDFLARE_ACCOUNT_ID": "acct",
        "IMAGE_TAG": "v1",
        "CF_KV_ID": "kvid",
        "CF_D1_ID": "d1id",
        "CF_VECTORIZE_ID": "vecidx",
        "PUBLIC_URL": "PUBLIC-URL-SENTINEL",
    }.items():
        monkeypatch.setenv(k, v)
    tpl = _SCRIPT.parent.parent / "wrangler.deploy.template.jsonc"
    cfg = json.loads(deploy_cf._strip_jsonc(deploy_cf.render_template(str(tpl))))
    binding = cfg["d1_databases"][0]
    assert binding["database_name"] == "wet-docs"
    assert binding["migrations_dir"] == "migrations"
    assert deploy_cf._d1_database_names(cfg) == ["wet-docs"]


@pytest.mark.skipif(shutil.which("node") is None, reason="node not on PATH")
def test_cf_deploy_mjs_migrates_before_deploy(tmp_path):
    """`npm run cf:deploy` is the second deploy path and carried the same gap.

    Hermetic: the script resolves its config relative to cwd, so a synthetic
    wrangler.jsonc in tmp_path keeps this off the real repo config."""
    (tmp_path / "wrangler.jsonc").write_text(
        '{"name":"w",'
        '"containers":[{"image":"registry.cloudflare.com/<YOUR_ACCOUNT_ID>/wet-mcp:t"}],'
        '"d1_databases":[{"binding":"D1","database_name":"wet-docs",'
        '"database_id":"x","migrations_dir":"migrations"}],'
        '"vars":{"PUBLIC_URL":"<YOUR_PUBLIC_URL>"}}',
        encoding="utf-8",
    )
    node = shutil.which("node")
    assert node is not None  # guaranteed by the skipif above; also narrows for ty
    out = subprocess.run(
        [node, str(_SCRIPT.parent / "cf-deploy.mjs"), "--dry-run"],
        cwd=tmp_path,
        env={
            **os.environ,
            "CLOUDFLARE_API_TOKEN": "token-sentinel",
            "CLOUDFLARE_ACCOUNT_ID": "abc123",
            "PUBLIC_URL": "https://example.invalid",
        },
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert out.returncode == 0, out.stderr
    assert "d1 migrations apply wet-docs --remote" in out.stdout
    assert out.stdout.index("d1 migrations apply") < out.stdout.index("deploy --config")
    # The resolved temp config must be cleaned up even on the dry-run path.
    assert not list(tmp_path.glob(".wrangler-deploy-*.jsonc"))


def test_every_migration_file_is_matched_by_wrangler_glob():
    """wrangler applies migrations_dir/*.sql in lexical order; a file that does
    not match (wrong extension / nested) would be skipped silently."""
    migrations = _SCRIPT.parent.parent / "migrations"
    files = sorted(p.name for p in migrations.iterdir() if p.is_file())
    assert files == sorted(p.name for p in migrations.glob("*.sql"))
    assert files, "migrations/ must not be empty"
