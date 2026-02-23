"""WET MCP Server entry point."""

import sys


def _warmup() -> None:
    """Pre-download models and run setup to avoid first-run delays.

    Run this before adding wet-mcp to your MCP config:
        uvx --python 3.13 wet-mcp warmup

    This installs SearXNG, Playwright/Chromium, and downloads the local
    embedding + reranking models (~1.1 GB total) so the first real
    connection does not timeout.
    """
    print("WET MCP warmup: running first-time setup...")

    # 1. Run auto-setup (SearXNG + Playwright)
    print("  Step 1/3: Installing SearXNG and Playwright...")
    from wet_mcp.setup import run_auto_setup

    run_auto_setup()
    print("  SearXNG and Playwright setup complete.")

    # 2. Check API keys -- if valid cloud keys exist, skip local download
    from wet_mcp.config import settings

    keys = settings.setup_api_keys()
    if keys:
        print(f"  API keys found: {', '.join(keys.keys())}")
        print("  Step 2/3: Validating cloud embedding models...")

        from wet_mcp.embedder import init_backend
        from wet_mcp.server import _EMBEDDING_CANDIDATES

        model = settings.resolve_embedding_model()
        candidates = [model] if model else _EMBEDDING_CANDIDATES

        cloud_ok = False
        for candidate in candidates:
            try:
                backend = init_backend("litellm", candidate)
                dims = backend.check_available()
                if dims > 0:
                    print(f"  Cloud embedding ready: {candidate} (dims={dims})")
                    cloud_ok = True
                    break
            except Exception:
                continue

        if cloud_ok:
            # Check reranker too
            print("  Step 3/3: Validating cloud reranker...")
            rerank_model = settings.resolve_rerank_model()
            if rerank_model:
                from wet_mcp.reranker import init_reranker

                try:
                    reranker = init_reranker("litellm", rerank_model)
                    if reranker.check_available():
                        print(f"  Cloud reranker ready: {rerank_model}")
                        print("Warmup complete! Cloud models will be used.")
                        return
                except Exception:
                    pass

            print("Warmup complete! Cloud embedding will be used.")
            return

        print("  Cloud embedding not available, falling back to local models...")

    # 3. Download local embedding model
    print("  Step 2/3: Downloading local embedding model (~570 MB)...")
    print("  This may take a few minutes on first run.")

    local_embed_model = settings.resolve_local_embedding_model()
    from qwen3_embed import TextEmbedding

    embed_model = TextEmbedding(model_name=local_embed_model)
    result = list(embed_model.embed(["warmup test"]))
    if result:
        print(f"  Local embedding ready (dims={len(result[0])})")

    # 4. Download local reranker model
    if settings.rerank_enabled:
        print("  Step 3/3: Downloading local reranker model (~570 MB)...")
        local_rerank_model = settings.resolve_local_rerank_model()
        from qwen3_embed import TextCrossEncoder

        reranker = TextCrossEncoder(model_name=local_rerank_model)
        scores = list(reranker.rerank("test query", ["test document"]))
        if scores:
            print("  Local reranker ready")
    else:
        print("  Step 3/3: Reranking disabled, skipping.")

    print("Warmup complete!")


def _cli() -> None:
    """CLI dispatcher: server (default), warmup, or setup-sync subcommand."""
    if len(sys.argv) >= 2 and sys.argv[1] == "warmup":
        _warmup()
    elif len(sys.argv) >= 2 and sys.argv[1] == "setup-sync":
        from wet_mcp.sync import setup_sync

        remote_type = sys.argv[2] if len(sys.argv) >= 3 else "drive"
        setup_sync(remote_type)
    else:
        from wet_mcp.server import main

        main()


if __name__ == "__main__":
    _cli()
