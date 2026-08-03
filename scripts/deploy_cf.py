#!/usr/bin/env python3
"""Build + push + deploy this MCP server's Cloudflare Worker+Container.

Turns the manual CF redeploy recipe into one repeatable command. Reads the
gitignored ``wrangler.deploy.jsonc`` (real account/KV/D1/Vectorize IDs) for the
container image name + account, builds the ``http`` target, pushes to the CF
managed registry, **applies the D1 migrations in** ``migrations/``, deploys,
waits for the container rollout to finish (STATE=ready) so you never verify
against a half-rolled old image, then runs a **credential-free canary gate** and
**auto-rolls-back** if it fails.

Why the migration step: ``wrangler deploy`` does not apply D1 migrations, and
the ``migrations_dir`` key on the D1 binding only tells ``wrangler d1
migrations *`` where to look. Nothing called it, so prod D1 silently drifted
from ``migrations/`` and a release shipping code that reads a new column failed
at runtime (issue #1617). It runs before the deploy so the schema is never
behind the code. The CF API token therefore needs D1:edit in addition to
Workers/Containers edit.

Set CLOUDFLARE_API_TOKEN in the environment (any secret manager works), then run
from the repo root:

    export CLOUDFLARE_API_TOKEN=...                       # however you store secrets
    python scripts/deploy_cf.py                           # tag defaults to b-<short-sha>
    ... python scripts/deploy_cf.py --tag b10-abc1234     # explicit tag
    ... python scripts/deploy_cf.py --skip-build          # reuse a built image
    ... python scripts/deploy_cf.py --dry-run             # print the plan only
    ... python scripts/deploy_cf.py --no-canary           # skip the post-deploy gate

The maintainer injects the token via ``skret`` (one option), e.g.:
    MSYS_NO_PATHCONV=1 skret run -e dev --path=/n24q02m/dev -- python scripts/deploy_cf.py

Requires: CLOUDFLARE_API_TOKEN in env, docker, and ``bunx wrangler``. The CF container
registry only pulls from registry.cloudflare.com/<account>/... (not ghcr), so the
local image is tagged to that path before ``wrangler containers push``.

Why the rollout wait: a heavy image (wet ~6GB) keeps serving OLD Durable Object
instances for minutes after deploy (``containers list`` STATE=provisioning);
verifying during that window shows stale behaviour. See docs/cf-deploy.md.

Why the canary gate: the unit / T0 suite cannot reach the CF-glue layer
(worker.ts CONTAINER_ENV_KEYS forwarding, container HOST bind, JWT signing keys),
which is exactly where the painful deploy regressions live. The gate is
credential-free (no per-server secrets needed) and catches the three that have
actually happened: (A) ``MCP_RELAY_PASSWORD`` dropped from the forward list ->
``/authorize`` serves the form with no login front door = open self-service relay;
(B) the bearer gate dropped -> ``/mcp`` no longer 401s; (C) ephemeral per-instance
JWT keys -> ``/.well-known/jwks.json`` ``kid`` changes between requests (the
/token-signs-with-A, /mcp-verifies-with-B -> 401 bug). On failure the previously
deployed image tag is redeployed automatically. A full authenticated
protocol round-trip (self-auth + setup + tool calls) stays in
``scripts/cf_full_flow.py``, which needs the per-server runtime secrets.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

# Windows consoles default to cp1252; wrangler emits box-drawing chars (│) and
# emoji. Make our own prints utf-8-safe so a captured status line can never crash
# the deploy on the encode side (the decode side is handled per-subprocess).
for _stream in (sys.stdout, sys.stderr):
    with contextlib.suppress(AttributeError, ValueError):
        _stream.reconfigure(encoding="utf-8", errors="replace")

DEPLOY_CONFIG = "wrangler.deploy.jsonc"
TEMPLATE_CONFIG = "wrangler.deploy.template.jsonc"


def render_template(path: str) -> str:
    """Substitute ``${VAR}`` tokens in the committed deploy template from the
    environment.

    CI runs ``deploy_cf.py --from-template`` to reconstruct the gitignored
    ``wrangler.deploy.jsonc`` from the committed placeholder template plus the
    real IDs, which arrive as env vars (GitHub Actions secrets synced from
    skret). Fails loudly if a referenced var is missing so a half-substituted
    config never reaches ``wrangler deploy``.
    """
    text = Path(path).read_text(encoding="utf-8")

    def _sub(m: re.Match[str]) -> str:
        val = os.environ.get(m.group(1))
        if val is None:
            raise SystemExit(f"template var ${{{m.group(1)}}} not set in environment")
        return val

    return re.sub(r"\$\{([A-Z0-9_]+)\}", _sub, text)


def _strip_jsonc(text: str) -> str:
    """Strip full-line // comments + trailing commas so json.loads accepts our
    deploy.jsonc. Inline // after values is intentionally NOT stripped (would
    corrupt https:// URLs); our deploy.jsonc keeps comments on their own lines."""
    lines = [ln for ln in text.splitlines() if not re.match(r"\s*//", ln)]
    body = "\n".join(lines)
    body = re.sub(r",(\s*[}\]])", r"\1", body)  # trailing commas
    return body


def _load_deploy_config(repo: Path) -> dict:
    path = repo / DEPLOY_CONFIG
    if not path.exists():
        sys.exit(
            f"{DEPLOY_CONFIG} not found in {repo}. It is gitignored (real IDs); "
            "reconstruct it from the committed wrangler.jsonc + CF resource IDs first."
        )
    return json.loads(_strip_jsonc(path.read_text(encoding="utf-8")))


def _short_sha(repo: Path) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "--short", "HEAD"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=True,
    ).stdout.strip()


def _run(cmd: list[str], *, dry: bool, cwd: Path | None = None) -> None:
    print(f"  $ {' '.join(cmd)}")
    if dry:
        return
    subprocess.run(cmd, cwd=str(cwd) if cwd else None, check=True)


def _image_parts(cfg: dict) -> tuple[str, str, str]:
    """Return (registry_base_without_tag, account_id, image_name) from the
    deploy config's first container image ref
    registry.cloudflare.com/<account>/<name>:<tag>."""
    ref = cfg["containers"][0]["image"]
    base = ref.rsplit(":", 1)[0]  # drop existing tag
    m = re.match(r"registry\.cloudflare\.com/([0-9a-f]+)/(.+)$", base)
    if not m:
        sys.exit(
            f"unexpected image ref (need registry.cloudflare.com/<acct>/<name>): {ref}"
        )
    return base, m.group(1), m.group(2)


def _d1_database_names(cfg: dict) -> list[str]:
    """D1 database names to migrate, read from the RENDERED deploy config.

    Never read these from the committed ``wrangler.jsonc``: it carries
    placeholder resource IDs, so a migration aimed at it would target the wrong
    (or no) database."""
    return [
        str(db["database_name"])
        for db in (cfg.get("d1_databases") or [])
        if db.get("database_name")
    ]


def _apply_d1_migrations(repo: Path, cfg: dict, *, dry: bool) -> None:
    """Apply ``migrations/`` to the remote D1 BEFORE the new worker rolls out.

    ``wrangler deploy`` does not run D1 migrations. The ``migrations_dir`` key on
    the D1 binding only tells ``wrangler d1 migrations *`` where to look, so
    before this step existed no deploy path touched the remote schema and prod
    D1 drifted from ``migrations/`` (issue #1617).

    Order is load-bearing: schema first, then code. Running this after
    ``wrangler deploy`` opens a live window in which the new container queries
    columns that do not exist yet.

    Forward-only by design, so ``_rollback`` deliberately does not undo it: every
    migration here is additive (CREATE / ADD COLUMN), which the previous image
    tolerates, whereas reverting a column the rolled-back canary already wrote to
    would lose data.

    ``wrangler d1 migrations apply`` skips its confirmation prompt when it
    detects a non-interactive/CI environment, so no extra flag is needed here.
    """
    names = _d1_database_names(cfg)
    if not names:
        print("  no d1_databases in the deploy config; nothing to migrate.")
        return
    for db in names:
        _run(
            [
                "bunx",
                "wrangler",
                "d1",
                "migrations",
                "apply",
                db,
                "--remote",
                "--config",
                DEPLOY_CONFIG,
            ],
            dry=dry,
            cwd=repo,
        )


def _public_url(cfg: dict) -> str:
    url = str((cfg.get("vars") or {}).get("PUBLIC_URL", "")).rstrip("/")
    if not url:
        sys.exit(
            "PUBLIC_URL missing from deploy config vars; cannot run the canary "
            "gate. Add it or pass --no-canary."
        )
    return url


def _set_image_tag(repo: Path, full_ref: str) -> None:
    """Rewrite the deploy.jsonc image line in place so `wrangler deploy` ships the
    tag we just pushed (gitignored file, safe to edit)."""
    path = repo / DEPLOY_CONFIG
    text = path.read_text(encoding="utf-8")
    new = re.sub(
        r'("image":\s*")registry\.cloudflare\.com/[^"]+(")',
        rf"\g<1>{full_ref}\g<2>",
        text,
        count=1,
    )
    path.write_text(new, encoding="utf-8")


def _wait_ready(worker: str, *, dry: bool, timeout_s: int = 600) -> None:
    """Poll `wrangler containers list` until the worker leaves provisioning."""
    if dry:
        print(f"  (dry-run) would poll containers list until {worker} STATE=ready")
        return
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        out = (
            subprocess.run(
                ["bunx", "wrangler", "containers", "list"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            ).stdout
            or ""
        )
        line = next((ln for ln in out.splitlines() if worker in ln), "")
        print(f"  [rollout] {line.strip() or '(no row yet)'}")
        if line and "provisioning" not in line.lower():
            print(f"  rollout complete: {worker} is no longer provisioning.")
            return
        time.sleep(25)
    print(f"  WARNING: {worker} still provisioning after {timeout_s}s — verify later.")


# --------------------------------------------------------------------------- #
# Canary gate (credential-free) + auto-rollback                               #
# --------------------------------------------------------------------------- #


def _get(url: str, *, timeout: int = 12) -> tuple[int, dict[str, str], str]:
    """GET following redirects. Return (status, lowercased-headers, final_url)."""
    req = urllib.request.Request(url, method="GET", headers={"User-Agent": "cf-canary"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            hdrs = {k.lower(): v for k, v in resp.headers.items()}
            return resp.status, hdrs, resp.geturl()
    except urllib.error.HTTPError as e:  # 4xx/5xx still carry headers we need
        hdrs = {k.lower(): v for k, v in (e.headers or {}).items()}
        return e.code, hdrs, e.url or url
    except (urllib.error.URLError, TimeoutError, OSError):
        # unreachable / TLS / timeout: status 0 makes every gate fail, which is
        # the correct canary verdict (a deploy that is not reachable must roll back)
        return 0, {}, url


def _gate_a(public_url: str) -> bool:
    """/authorize must land on /login = the shared relay-password front door is on."""
    authz = (
        f"{public_url}/authorize?response_type=code&client_id=local-browser"
        f"&redirect_uri={public_url}/callback-done&state=x"
        f"&code_challenge=x&code_challenge_method=S256&scope=offline_access"
    )
    _, _, final = _get(authz)
    ok = "/login" in final
    detail = (
        "OK" if ok else "FAIL: no /login -> OPEN SELF-SERVICE RELAY (Gate A dropped)"
    )
    print(f"  [canary] Gate A  /authorize -> {final}  {detail}")
    return ok


def _gate_b(public_url: str) -> bool:
    """/mcp must 401 with a WWW-Authenticate: Bearer challenge."""
    status, hdrs, _ = _get(f"{public_url}/mcp")
    ok = status == 401 and "bearer" in hdrs.get("www-authenticate", "").lower()
    detail = "OK" if ok else f"FAIL (status={status}, bearer challenge missing)"
    print(f"  [canary] Gate B  /mcp -> {status}  {detail}")
    return ok


def _jwks_kid(public_url: str) -> str | None:
    # Single fetch WITH a User-Agent: a bare urlopen (no UA) gets challenged by
    # Cloudflare in front of the Worker and fails, which previously made this
    # return None even though the endpoint serves a valid kid.
    try:
        req = urllib.request.Request(
            f"{public_url}/.well-known/jwks.json", headers={"User-Agent": "cf-canary"}
        )
        with urllib.request.urlopen(req, timeout=12) as resp:
            if resp.status != 200:
                return None
            data = json.loads(resp.read().decode("utf-8"))
        keys = data.get("keys") or []
        return keys[0].get("kid") if keys else None
    except Exception:
        return None


def _gate_kid_stable(public_url: str, *, tries: int = 10, delay: int = 6) -> bool:
    """jwks kid must be identical across requests; a varying kid means ephemeral
    per-instance signing keys (/token signs with A, /mcp verifies with B -> 401).

    A just-rolled container may not serve jwks for a few seconds, so collect over
    a settle window: need >=3 successful reads (all identical = stable). All-None
    after the window = the endpoint genuinely never served a key."""
    kids: list[str] = []
    for _ in range(tries):
        k = _jwks_kid(public_url)
        if k is not None:
            kids.append(k)
            if len(kids) >= 3:
                break
        time.sleep(delay)
    uniq = set(kids)
    ok = len(kids) >= 3 and len(uniq) == 1
    if not kids:
        detail = "FAIL: jwks served no kid after settle window (endpoint down?)"
    elif len(uniq) > 1:
        detail = "FAIL: kid varies -> ephemeral per-instance keys"
    else:
        detail = "OK"
    print(f"  [canary] JWKS    kid -> {uniq or '{}'}  {detail}")
    return ok


def _retry_gate(fn, public_url: str, *, tries: int = 10, delay: int = 6) -> bool:
    """Poll a boolean gate until it passes or the settle window is exhausted.

    STATE=ready means the Durable Object is provisioned, NOT that the in-container
    app is already serving. A heavy Python container (cryptg/telethon/uvicorn)
    needs ~10-15s after ready before /authorize fronts /login, so a single
    check-once gate false-fails and triggers an unnecessary rollback. Mirror the
    settle-window approach _gate_kid_stable already uses."""
    for i in range(tries):
        if fn(public_url):
            return True
        if i < tries - 1:
            time.sleep(delay)
    return False


def _canary(public_url: str, *, dry: bool) -> bool:
    if dry:
        print(
            "  (dry-run) would run canary: Gate A /authorize->/login, "
            "Gate B /mcp 401, JWKS kid-stable"
        )
        return True
    print(f"Canary gate against {public_url} (credential-free):")
    results = [
        _retry_gate(_gate_a, public_url),
        _retry_gate(_gate_b, public_url),
        _gate_kid_stable(public_url),
    ]
    return all(results)


def _rollback(repo: Path, worker: str, prev_ref: str, *, dry: bool) -> None:
    print(f"  CANARY FAILED -> rolling back to previous image {prev_ref}")
    if dry:
        return
    _set_image_tag(repo, prev_ref)
    _run(
        ["bunx", "wrangler", "deploy", "--config", DEPLOY_CONFIG],
        dry=False,
        cwd=repo,
    )
    _wait_ready(worker, dry=False)
    print(f"  rolled back {worker} to {prev_ref}.")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Deploy this MCP server's CF Worker+Container."
    )
    p.add_argument("--tag", default="", help="image tag (default: b-<short-sha>)")
    p.add_argument(
        "--skip-build", action="store_true", help="reuse an already-built local image"
    )
    p.add_argument("--dry-run", action="store_true", help="print the plan, run nothing")
    p.add_argument(
        "--from-template",
        action="store_true",
        help="reconstruct wrangler.deploy.jsonc from the committed template + env (CI)",
    )
    p.add_argument(
        "--no-canary",
        action="store_true",
        help="skip the post-deploy canary gate (and its auto-rollback)",
    )
    args = p.parse_args(argv)

    repo = Path(__file__).resolve().parent.parent
    if args.from_template:
        (repo / DEPLOY_CONFIG).write_text(
            render_template(str(repo / TEMPLATE_CONFIG)), encoding="utf-8"
        )
        print(f"Rendered {DEPLOY_CONFIG} from {TEMPLATE_CONFIG} (CI mode).")
    cfg = _load_deploy_config(repo)
    worker = cfg["name"]
    base, _account, name = _image_parts(cfg)
    prev_ref = cfg["containers"][0]["image"]  # currently-deployed tag, for rollback
    tag = args.tag or f"b-{_short_sha(repo)}"
    local = f"{name}:{tag}"
    full = f"{base}:{tag}"

    print(f"Deploy {worker}: image {local} -> {full}")
    if not args.skip_build:
        print("[1/5] docker build --target http")
        _run(
            [
                "docker",
                "build",
                "--target",
                "http",
                "--build-arg",
                "SLIM=1",
                "-t",
                local,
                ".",
            ],
            dry=args.dry_run,
            cwd=repo,
        )
    print("[2/5] docker tag -> CF registry")
    _run(["docker", "tag", local, full], dry=args.dry_run)
    print("[3/5] wrangler containers push")
    _run(["bunx", "wrangler", "containers", "push", full], dry=args.dry_run, cwd=repo)
    # Schema before code, and only once the image is safely pushed: a build or
    # push failure must not leave prod D1 migrated ahead of any shipped worker.
    print("[4/5] wrangler d1 migrations apply --remote (schema before code)")
    _apply_d1_migrations(repo, cfg, dry=args.dry_run)
    print(f"[5/5] wrangler deploy --config {DEPLOY_CONFIG}")
    if not args.dry_run:
        _set_image_tag(repo, full)
    _run(
        ["bunx", "wrangler", "deploy", "--config", DEPLOY_CONFIG],
        dry=args.dry_run,
        cwd=repo,
    )

    print("Waiting for container rollout (avoid verifying a half-rolled old image)...")
    _wait_ready(worker, dry=args.dry_run)

    if args.no_canary:
        print(
            f"DONE (--no-canary): {worker} deployed at tag {tag}. "
            "Verify manually with scripts/cf_full_flow.py."
        )
        return 0

    if _canary(_public_url(cfg), dry=args.dry_run):
        print(
            f"DONE: {worker} deployed at tag {tag}, canary PASS. "
            "Run scripts/cf_full_flow.py for the authenticated tool round-trip."
        )
        return 0

    if prev_ref == full:
        print(
            "  CANARY FAILED but the previous image ref equals the just-deployed "
            "ref; not auto-rolling-back. Investigate manually."
        )
        return 1
    _rollback(repo, worker, prev_ref, dry=args.dry_run)
    print(f"FAILED: {worker} canary did not pass; rolled back to {prev_ref}.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
