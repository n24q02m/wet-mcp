import sys
import os

file_path = 'src/wet_mcp/sync.py'

with open(file_path, 'r') as f:
    lines = f.readlines()

start_line = -1
for i, line in enumerate(lines):
    if line.startswith('async def sync_full(db: DocsDB) -> dict:'):
        start_line = i
        break

if start_line == -1:
    print("Could not find sync_full definition")
    sys.exit(1)

# Find the end of sync_full (it ends before check_health)
end_line = -1
for i in range(start_line, len(lines)):
    if lines[i].startswith('async def check_health() -> bool:'):
        end_line = i
        break

if end_line == -1:
    print("Could not find check_health definition")
    sys.exit(1)

# Backtrack to find the last non-empty line before check_health
while end_line > start_line and not lines[end_line-1].strip():
    end_line -= 1

new_code = """
async def _check_sync_readiness() -> dict | None:
    \"\"\"Check if sync is enabled and configured correctly.\"\"\"
    if not settings.sync_enabled:
        return {"status": "disabled", "message": "Sync not configured"}

    if not settings.google_drive_client_id:
        return {
            "status": "error",
            "message": "GOOGLE_DRIVE_CLIENT_ID not configured",
        }

    if not _has_token_available():
        return {
            "status": "error",
            "message": "No Google Drive token available. "
            "Run setup_sync to complete OAuth setup.",
        }

    token = await _get_valid_token()
    if not token:
        return {
            "status": "error",
            "message": "Google Drive token expired and refresh failed. "
            "Run setup_sync to re-authenticate.",
        }
    return None


async def _pull_and_merge(db: DocsDB, db_path: Path, folder: str) -> dict:
    \"\"\"Pull remote DB and merge into local DB.\"\"\"
    from wet_mcp.db import DocsDB

    remote_db_path = await sync_pull(db_path, folder)
    if not remote_db_path:
        return {
            "libraries": 0,
            "versions": 0,
            "chunks": 0,
            "skipped": 0,
            "note": "No remote DB found",
        }

    try:
        # Open remote DB and export JSONL
        remote_db = DocsDB(remote_db_path, embedding_dims=0)
        remote_jsonl = remote_db.export_jsonl()
        remote_db.close()

        # Import into local DB (merge mode - skip existing)
        if remote_jsonl.strip():
            import_result = db.import_jsonl(remote_jsonl, mode="merge")
            logger.info(f"Merged remote docs: {import_result}")
            return import_result
        else:
            return {
                "libraries": 0,
                "versions": 0,
                "chunks": 0,
                "skipped": 0,
            }
    except Exception as e:
        logger.error(f"Merge failed: {e}")
        return {"error": str(e)}
    finally:
        # Cleanup temp file
        remote_db_path.unlink(missing_ok=True)
        try:
            remote_db_path.parent.rmdir()
        except OSError:
            pass


async def sync_full(db: DocsDB) -> dict:
    \"\"\"Full sync cycle: pull -> merge -> push.

    Returns:
        Dict with sync results.
    \"\"\"
    readiness_error = await _check_sync_readiness()
    if readiness_error:
        return readiness_error

    db_path = settings.get_db_path()
    folder = settings.sync_folder

    # 1. Pull & Merge
    pull_result = await _pull_and_merge(db, db_path, folder)

    # 2. Push local DB to remote
    push_ok = await sync_push(db_path, folder)

    return {
        "status": "ok",
        "pull": pull_result,
        "push": {"success": push_ok},
    }
"""

with open(file_path, 'w') as f:
    f.writelines(lines[:start_line])
    f.write(new_code)
    f.write("\n\n")
    f.writelines(lines[end_line:])

print("Successfully refactored sync_full")
