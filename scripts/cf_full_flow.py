"""CF wet-mcp live OAuth full-flow self-test harness.

Drives the deployed wet-mcp Cloudflare Worker (Worker + per-sub Container + KV +
D1 + Vectorize) end-to-end against a public endpoint. wet is a LOCAL-FORM server
(like mnemo/imagine/email, NOT delegated like notion): the /authorize gate is just
the relay password, so the whole flow is fully autonomous -- no third-party consent.

Flow (authorization_code + PKCE, DCR public client; ported verbatim from the
mnemo/imagine/email CF harnesses):
  1. DCR register   -- POST /register (RFC 7591) -> client_id
  2. password-grant -- GET /authorize -> POST /login (Gate A relay password) -> form
  3. save creds     -- POST /authorize?nonce=... {provider key} (retry-on-500 for the
                       E.1 outbound-interception race). wet's _require_credentials()
                       gates every tool on the per-sub vault holding >=1 provider key
                       (JINA/GEMINI/OPENAI/COHERE); it does NOT read the server-side
                       forwarded JINA from os.environ, so a real user must submit one.
                       The harness submits whatever key skret /wet-mcp/prod injects.
  4. token          -- POST /token (code + verifier) -> bearer JWT
  5. tool call      -- config(status) + search(action="search"); assert the search
                       path resolves real results (URLs) over the CF deployment.

Secrets from env: Gate A login password MCP_RELAY_PASSWORD (or RELAY_PW) from skret
/oci-vm-prod/prod (infra-shared); >=1 provider key (JINA_AI_API_KEY preferred) from
skret /wet-mcp/prod -- compose both namespaces.

Run modes:
  (default)            full flow: config(status) + search, assert real results.
  --save-only          configure one sub (submit provider key) + dump the token
                       (recreate-gate setup half of the state-survives-recreate test).
  --auth-only          replay the SAME token (same sub) and search again WITHOUT
                       re-saving (recreate-gate verify: the sub vault survived KV).
  --two-sub-isolation  two distinct subs; assert each authorizes to a distinct sub
                       (the relay-login mints a fresh random sub per /authorize).

Examples:
  skret run -e prod --path=/oci-vm-prod/prod -- \
    skret run -e prod --path=/wet-mcp/prod -- \
      python scripts/cf_full_flow.py
  ... -- python scripts/cf_full_flow.py --endpoint https://wet.n24q02m.com
  ... -- python scripts/cf_full_flow.py --save-only
  ... -- python scripts/cf_full_flow.py --auth-only
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import json as _json
import os
import re
import secrets
import sys
import time
import urllib.parse
from pathlib import Path

# No hardcoded host: set CF_ENDPOINT or pass --endpoint https://<your-worker-domain>.
# This self-tests YOUR deployed CF server; creds come from env (MCP_RELAY_PASSWORD +
# provider keys) -- the maintainer injects them via skret, but any export works.
DEFAULT_ENDPOINT = os.environ.get("CF_ENDPOINT", "")

SEARCH_QUERY = "cloudflare workers durable objects"
EXTRACT_URL = "https://example.com"


def _password() -> str:
    pw = os.environ.get("RELAY_PW") or os.environ.get("MCP_RELAY_PASSWORD")
    if not pw:
        raise SystemExit(
            "MCP_RELAY_PASSWORD (or RELAY_PW) is required for the password-grant "
            "login gate. It lives in skret /oci-vm-prod/prod (infra-shared), NOT "
            "/wet-mcp/prod -- compose both namespaces."
        )
    return pw


def _creds() -> dict[str, str]:
    """Per-sub credential form payload. wet's `_require_credentials()` gates every
    tool on the per-sub vault holding at least one provider key (JINA / GEMINI /
    OPENAI / COHERE) -- it does NOT read the server-side forwarded JINA from
    os.environ. So a real user must submit a key; the harness submits whichever
    provider key skret /wet-mcp/prod injects (JINA preferred)."""
    creds: dict[str, str] = {}
    for env_name in (
        "JINA_AI_API_KEY",
        "GEMINI_API_KEY",
        "OPENAI_API_KEY",
        "COHERE_API_KEY",
        "XAI_API_KEY",
    ):
        v = os.environ.get(env_name)
        if v:
            creds[env_name] = v
    if not creds:
        raise SystemExit(
            "No provider key in env (JINA_AI_API_KEY / GEMINI_API_KEY / "
            "OPENAI_API_KEY / COHERE_API_KEY). skret /wet-mcp/prod injects them; "
            "wet's per-sub gate requires at least one to authorize tool calls."
        )
    return creds


class _SaveRetry(Exception):
    pass


def get_token(endpoint: str, creds: dict[str, str], *, save_retries: int = 8) -> str:
    """Run the full OAuth flow, retrying on a transient 500 at the credential save
    step (CF Containers outbound-interception race on cold-started instances; E.1).
    Each retry restarts from DCR so the nonce is fresh. ``creds`` is the /authorize
    form payload (EMPTY for wet: search/extract + embed are server-side)."""
    import httpx  # lazy: keep --help importable without httpx installed

    last: Exception | None = None
    for attempt in range(save_retries):
        try:
            return _get_token_once(httpx, endpoint, creds)
        except _SaveRetry as e:
            last = e
            print(
                f"get_token: save 500 (interception race), retry {attempt + 1}/{save_retries}"
            )
            time.sleep(3)
    raise RuntimeError(f"get_token failed after {save_retries} retries: {last}")


def _get_token_once(httpx, endpoint: str, creds: dict[str, str]) -> str:
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode()
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
        .rstrip(b"=")
        .decode()
    )
    ru = "http://localhost:9999/cb"
    pw = _password()
    with httpx.Client(timeout=120, follow_redirects=False) as c:
        cid = c.post(
            f"{endpoint}/register",
            json={
                "client_name": "cf-verify",
                "redirect_uris": [ru],
                "grant_types": ["authorization_code", "refresh_token"],
                "response_types": ["code"],
                "token_endpoint_auth_method": "none",
                "scope": "offline_access",
            },
        ).json()["client_id"]
        az = c.get(
            f"{endpoint}/authorize",
            params={
                "response_type": "code",
                "client_id": cid,
                "redirect_uri": ru,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
                "state": "st",
                "scope": "offline_access",
            },
        )
        nxt = urllib.parse.parse_qs(
            urllib.parse.urlparse(az.headers["location"]).query
        )["next"][0]
        lg = c.post(f"{endpoint}/login", data={"next": nxt, "password": pw})
        url = lg.headers["location"]
        url = url if url.startswith("http") else endpoint + url
        form_html = c.get(url).text
        m = re.search(r"/authorize\?nonce=([A-Za-z0-9_\-]+)", form_html)
        assert m, "nonce not found in form"
        nonce = m.group(1)
        sub = c.post(f"{endpoint}/authorize", params={"nonce": nonce}, json=creds)
        if sub.status_code == 500 and "save credentials" in sub.text:
            raise _SaveRetry(sub.text[:120])
        assert sub.status_code == 200, (sub.status_code, sub.text[:300])
        data = sub.json()
        assert data.get("ok"), data
        code = urllib.parse.parse_qs(urllib.parse.urlparse(data["redirect_url"]).query)[
            "code"
        ][0]
        tok = c.post(
            f"{endpoint}/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": ru,
                "client_id": cid,
                "code_verifier": verifier,
            },
        )
        assert tok.status_code == 200, (tok.status_code, tok.text[:300])
        return tok.json()["access_token"]


def _sub_of(token: str) -> str:
    payload = _json.loads(base64.urlsafe_b64decode(token.split(".")[1] + "=="))
    return payload.get("sub", "?")


async def _call(s, label, tool, args, *, retries=20, delay=8):
    """Call a tool, retrying while the sub is still propagating (KV cross-colo
    eventual consistency after the setup write; E.2). Returns the concatenated
    text payload, or None on give-up."""
    for i in range(retries):
        try:
            res = await s.call_tool(tool, args)
            txt = "".join(getattr(b, "text", "") for b in res.content)
            if "awaiting_setup" in txt or "Credentials not configured" in txt:
                print(f"{label}: awaiting_setup (KV propagating) try {i + 1}/{retries}")
                await asyncio.sleep(delay)
                continue
            print(f"{label} OK:", txt[:320].replace("\n", " "))
            return txt
        except Exception as e:
            print(f"{label} ERR:", repr(e)[:300])
            return None
    print(f"{label}: gave up after {retries} tries")
    return None


def _assert_search_resolved(txt: str | None) -> None:
    """A real search result is a JSON listing with at least one http(s) URL and no
    hard error. A backend-misconfig (SearXNG vs Tavily) surfaces as an error string
    here -- that is a genuine CF-deployment finding, not a test bug."""
    assert txt is not None, "search returned no payload (gave up while not ready)"
    low = txt.lower()
    assert not low.startswith("error"), f"search returned an error: {txt[:300]}"
    assert "http" in low, f"search did not return any URL result: {txt[:300]}"
    print("ASSERT OK: search resolved real web results over the CF deployment.")


async def _session(endpoint: str, token: str):
    from mcp import ClientSession  # lazy: keep --help importable without mcp installed
    from mcp.client.streamable_http import streamablehttp_client

    return streamablehttp_client(
        f"{endpoint}/mcp", headers={"Authorization": f"Bearer {token}"}
    ), ClientSession


async def _run_search(s) -> str | None:
    return await _call(
        s,
        "SEARCH",
        "search",
        {"action": "search", "query": SEARCH_QUERY, "max_results": 3},
    )


async def _run_extract(s) -> str | None:
    return await _call(
        s,
        "EXTRACT",
        "extract",
        {"action": "extract", "urls": [EXTRACT_URL]},
    )


def _assert_extract_resolved(txt: str | None) -> None:
    """Assert that extract returned structured content from a real URL."""
    assert txt is not None, "extract returned no payload (gave up while not ready)"
    low = txt.lower()
    assert "http" in low, f"extract returned no URL: {txt[:300]}"
    assert any(field in low for field in ('"markdown"', '"clean_text"')), (
        f"extract returned no content field: {txt[:300]}"
    )
    print("ASSERT OK: extract resolved real page content over the CF deployment.")


def _token_file() -> Path:
    return Path(__file__).with_name(".wet_cf_token")


async def run_full(endpoint: str) -> None:
    token = get_token(endpoint, _creds())
    print("TOKEN OK len=", len(token), "sub=", _sub_of(token))
    transport, ClientSession = await _session(endpoint, token)
    async with transport as (r, w, _), ClientSession(r, w) as s:
        await s.initialize()
        tools = await s.list_tools()
        print("TOOLS:", [t.name for t in tools.tools])
        await _call(s, "CONFIG_STATUS", "config", {"action": "status"})
        txt = await _run_search(s)
        _assert_search_resolved(txt)
        extract_txt = await _run_extract(s)
        _assert_extract_resolved(extract_txt)
    print("FULL FLOW PASS.")


async def run_save_only(endpoint: str) -> None:
    token = get_token(endpoint, _creds())
    transport, ClientSession = await _session(endpoint, token)
    async with transport as (r, w, _), ClientSession(r, w) as s:
        await s.initialize()
        await _call(s, "CONFIG_STATUS", "config", {"action": "status"})
    # Dump the EXACT token so --auth-only replays the SAME JWT sub (relay-login mints
    # a fresh random sub per /authorize).
    _token_file().write_text(token)
    print(
        "SAVE-ONLY OK: sub configured=",
        _sub_of(token),
        "(token dumped for --auth-only)",
    )


async def run_auth_only(endpoint: str) -> None:
    tok_path = _token_file()
    if not tok_path.exists():
        raise SystemExit("No dumped token -- run --save-only first.")
    token = tok_path.read_text().strip()
    print("AUTH-ONLY: replaying saved token for sub=", _sub_of(token))
    transport, ClientSession = await _session(endpoint, token)
    async with transport as (r, w, _), ClientSession(r, w) as s:
        await s.initialize()
        txt = await _run_search(s)
        _assert_search_resolved(txt)
        extract_txt = await _run_extract(s)
        _assert_extract_resolved(extract_txt)
    print("AUTH-ONLY PASS: sub survived recreate (KV vault resolved, no re-save).")


async def run_two_sub_isolation(endpoint: str) -> None:
    token_a = get_token(endpoint, _creds())
    sub_a = _sub_of(token_a)
    token_b = get_token(endpoint, _creds())
    sub_b = _sub_of(token_b)
    print(f"sub A={sub_a}  sub B={sub_b}")
    if sub_a == sub_b:
        raise SystemExit(
            f"ISOLATION INCONCLUSIVE: both flows share sub {sub_a} (cannot test bleed)."
        )
    transport, ClientSession = await _session(endpoint, token_b)
    async with transport as (r, w, _), ClientSession(r, w) as s:
        await s.initialize()
        txt = await _run_search(s)
        _assert_search_resolved(txt)
    print(
        "TWO-SUB ISOLATION OK: distinct subs, sub B authorizes + searches independently."
    )


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="CF wet-mcp live OAuth full-flow self-test harness.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument(
        "--endpoint",
        default=DEFAULT_ENDPOINT,
        required=not DEFAULT_ENDPOINT,
        help=f"Deployed wet endpoint (default: {DEFAULT_ENDPOINT})",
    )
    mode = p.add_mutually_exclusive_group()
    mode.add_argument(
        "--save-only",
        action="store_true",
        help="Configure one sub (empty form) + dump the token, then exit (recreate setup).",
    )
    mode.add_argument(
        "--auth-only",
        action="store_true",
        help="Replay the SAME token + search WITHOUT re-saving (recreate verify).",
    )
    mode.add_argument(
        "--two-sub-isolation",
        action="store_true",
        help="Two distinct subs; assert sub B authorizes + searches independently.",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.save_only:
        asyncio.run(run_save_only(args.endpoint))
    elif args.auth_only:
        asyncio.run(run_auth_only(args.endpoint))
    elif args.two_sub_isolation:
        asyncio.run(run_two_sub_isolation(args.endpoint))
    else:
        asyncio.run(run_full(args.endpoint))
    return 0


if __name__ == "__main__":
    sys.exit(main())
