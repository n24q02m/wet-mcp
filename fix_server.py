with open("src/wet_mcp/server.py") as f:
    content = f.read()

# Replace _setup_auto_sync with type-safe version
old_sync = r'''
def _setup_auto_sync() -> None:
    """Start auto-sync if enabled."""
    if settings.sync_enabled:
        from wet_mcp.sync import start_auto_sync

        start_auto_sync(_docs_db)
'''.strip()

new_sync = r'''
def _setup_auto_sync() -> None:
    """Start auto-sync if enabled."""
    if settings.sync_enabled and _docs_db:
        from wet_mcp.sync import start_auto_sync

        start_auto_sync(_docs_db)
'''.strip()

new_content = content.replace(old_sync, new_sync)

if content != new_content:
    with open("src/wet_mcp/server.py", "w") as f:
        f.write(new_content)
    print("Successfully patched src/wet_mcp/server.py")
else:
    print("Could not find _setup_auto_sync function to patch")
    # Print content snippet for debugging
    print(
        content[
            content.find("def _setup_auto_sync") : content.find("def _setup_auto_sync")
            + 200
        ]
    )
