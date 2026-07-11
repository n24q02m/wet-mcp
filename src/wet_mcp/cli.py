"""Console-script entry: mounts the shared mcp_core CLI builder.

Bare invocation and any leading-dash argv (e.g. --http) start the server
exactly as before; subcommands run one-shot operator actions.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os

from mcp_core import build_cli


def _serve(argv: list[str]) -> int | None:
    from wet_mcp.server import main as server_main

    server_main()
    return 0


def _configure_auth(p: argparse.ArgumentParser) -> None:
    p.add_argument(
        "provider", choices=["google"], help="Credential provider to authorize"
    )
    p.add_argument(
        "--client-id",
        default=None,
        help="BYO OAuth client id (must be paired with --client-secret)",
    )
    p.add_argument("--client-secret", default=None, help="BYO OAuth client secret")


def _handle_auth(args: argparse.Namespace) -> int:
    # Single-user / local machine only: writes the token via the local store.
    if args.client_id or args.client_secret:
        from mcp_core.auth import resolve_bundled_client

        from wet_mcp.config import _GOOGLE_CLIENT_SPEC

        resolved = resolve_bundled_client(
            _GOOGLE_CLIENT_SPEC, cli_id=args.client_id, cli_secret=args.client_secret
        )
        os.environ[_GOOGLE_CLIENT_SPEC.env_id] = resolved.client_id
        os.environ[_GOOGLE_CLIENT_SPEC.env_secret] = resolved.client_secret
    from wet_mcp.setup_tool import run_setup_sync

    result = asyncio.run(run_setup_sync())
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("status") == "ok" else 1


def _handle_warmup(args: argparse.Namespace) -> int:
    from wet_mcp.setup_tool import run_warmup

    result = asyncio.run(run_warmup())
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("status") == "ok" else 1


def _configure_docs(p: argparse.ArgumentParser) -> None:
    p.add_argument("docs_action", choices=["reindex"], help="Docs index action")
    p.add_argument("library", help="Library name to reindex")


def _handle_docs(args: argparse.Namespace) -> int:
    from wet_mcp.server import make_docs_db

    # Standalone DB handle (not the lifespan-owned global _docs_db) so this
    # subcommand works without a running server.
    db = make_docs_db()
    lib = db.get_library(args.library)
    if not lib:
        result = {"error": f"Library '{args.library}' not found in index"}
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1
    ver = db.get_best_version(lib["id"])
    if ver:
        db.clear_version_chunks(ver["id"])
    result = {
        "status": "cleared",
        "library": args.library,
        "hint": "Next docs search will re-index",
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def _extras() -> dict:
    return {
        "auth": (_configure_auth, _handle_auth),
        "warmup": _handle_warmup,
        "docs": (_configure_docs, _handle_docs),
    }


def _version() -> str:
    from wet_mcp import __version__

    return __version__


def main() -> int:
    return build_cli("wet-mcp", serve=_serve, extra=_extras(), version=_version())(None)
