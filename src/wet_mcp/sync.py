"""Google Drive sync for docs database.

Syncs the docs database (libraries + chunks) across machines using
Google Drive API. Only docs data is synced -- web cache (search/extract)
is ephemeral and not synced.

Sync flow:
1. Authenticate via OAuth Device Code flow
2. Push: upload local DB to Google Drive folder
3. Pull: download remote DB, merge via JSONL export/import
4. Auto-sync: periodic push/pull in background

Auth flow (Device Code -- no browser redirect needed):
1. POST /device/code -> get user_code + verification_url
2. User visits URL, enters code (or relay sends it)
3. Poll /token until authorized
4. Save access_token + refresh_token locally
5. Auto-refresh when expired
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

import httpx
from loguru import logger

from wet_mcp.config import settings

if TYPE_CHECKING:
    from wet_mcp.db import DocsDB

# Google OAuth endpoints
_DEVICE_CODE_URL = "https://oauth2.googleapis.com/device/code"
_TOKEN_URL = "https://oauth2.googleapis.com/token"
_DRIVE_API_BASE = "https://www.googleapis.com/drive/v3"
_DRIVE_UPLOAD_BASE = "https://www.googleapis.com/upload/drive/v3"

# OAuth scope: only access files created by this app
_SCOPE = "https://www.googleapis.com/auth/drive.file"

# Device code flow grant type
_DEVICE_CODE_GRANT = "urn:ietf:params:oauth:grant-type:device_code"

# Background sync task reference
_sync_task: asyncio.Task | None = None

# Token provider name for token_store
_TOKEN_PROVIDER = "google_drive"


# ---------------------------------------------------------------------------
# Token management
# ---------------------------------------------------------------------------


def _load_token() -> dict | None:
    """Load Google Drive OAuth token from local storage."""
    from wet_mcp.token_store import load_token

    return load_token(_TOKEN_PROVIDER)


def _save_token(token: dict) -> None:
    """Save Google Drive OAuth token to local storage."""
    from wet_mcp.token_store import save_token

    save_token(_TOKEN_PROVIDER, token)


def _has_token_available() -> bool:
    """Check if a Google Drive token is available."""
    return _load_token() is not None


async def _refresh_token(token: dict) -> dict | None:
    """Refresh an expired access token using the refresh_token.

    Returns updated token dict, or None if refresh failed.
    """
    refresh_token = token.get("refresh_token")
    client_id = token.get("client_id", settings.google_drive_client_id)
    client_secret = settings.google_drive_client_secret

    if not refresh_token or not client_id:
        logger.warning("Cannot refresh token: missing refresh_token or client_id")
        return None

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                _TOKEN_URL,
                data={
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token,
                },
                timeout=30.0,
            )

            if response.status_code != 200:
                logger.error(f"Token refresh failed: {response.text}")
                return None

            data = response.json()

            # Update token (keep existing refresh_token if not returned)
            updated = {
                "access_token": data["access_token"],
                "refresh_token": data.get("refresh_token", refresh_token),
                "expiry": time.time() + data.get("expires_in", 3600),
                "client_id": client_id,
                "token_type": data.get("token_type", "Bearer"),
            }
            _save_token(updated)
            logger.debug("Token refreshed successfully")
            return updated

    except Exception as e:
        logger.error(f"Token refresh error: {e}")
        return None


async def _get_valid_token() -> dict | None:
    """Get a valid (non-expired) access token, refreshing if needed.

    Returns token dict with valid access_token, or None.
    """
    token = _load_token()
    if not token:
        return None

    # Check expiry (refresh 60s before actual expiry)
    expiry = token.get("expiry", 0)
    if time.time() >= expiry - 60:
        logger.debug("Token expired, refreshing...")
        token = await _refresh_token(token)

    return token


# ---------------------------------------------------------------------------
# Google Drive API helpers
# ---------------------------------------------------------------------------


@dataclass
class DriveRequestOptions:
    params: dict | None = None
    json_data: dict | None = None
    content: bytes | None = None
    headers: dict | None = None
    timeout: float = 120.0


async def _drive_request(
    method: str,
    url: str,
    token: dict,
    options: DriveRequestOptions | None = None,
) -> httpx.Response:
    """Make an authenticated Google Drive API request."""
    opts = options or DriveRequestOptions()
    req_headers = {
        "Authorization": f"Bearer {token['access_token']}",
        **(opts.headers or {}),
    }

    async with httpx.AsyncClient() as client:
        response = await client.request(
            method,
            url,
            params=opts.params,
            json=opts.json_data,
            content=opts.content,
            headers=req_headers,
            timeout=opts.timeout,
        )

    return response


async def _find_or_create_folder(token: dict, folder_name: str) -> str | None:
    """Find or create a Google Drive folder by name.

    Returns folder ID, or None on failure.
    """
    # Search for existing folder
    query = (
        f"name='{folder_name}' and mimeType='application/vnd.google-apps.folder' "
        f"and trashed=false"
    )
    response = await _drive_request(
        "GET",
        f"{_DRIVE_API_BASE}/files",
        token,
        options=DriveRequestOptions(
            params={"q": query, "fields": "files(id,name)", "spaces": "drive"}
        ),
    )

    if response.status_code == 200:
        files = response.json().get("files", [])
        if files:
            return files[0]["id"]

    # Create new folder
    metadata: dict[str, Any] = {
        "name": folder_name,
        "mimeType": "application/vnd.google-apps.folder",
    }
    response = await _drive_request(
        "POST",
        f"{_DRIVE_API_BASE}/files",
        token,
        options=DriveRequestOptions(
            json_data=metadata,
            params={"fields": "id"},
        ),
    )

    if response.status_code == 200:
        return response.json().get("id")

    logger.error(f"Failed to create folder '{folder_name}': {response.text}")
    return None


async def _find_file_in_folder(
    token: dict, folder_id: str, file_name: str
) -> dict | None:
    """Find a file by name in a specific folder.

    Returns file metadata dict (id, name, modifiedTime), or None.
    """
    query = f"name='{file_name}' and '{folder_id}' in parents and trashed=false"
    response = await _drive_request(
        "GET",
        f"{_DRIVE_API_BASE}/files",
        token,
        options=DriveRequestOptions(
            params={
                "q": query,
                "fields": "files(id,name,modifiedTime)",
                "spaces": "drive",
            }
        ),
    )

    if response.status_code == 200:
        files = response.json().get("files", [])
        if files:
            return files[0]

    return None


async def _upload_file(
    token: dict,
    file_path: Path,
    folder_id: str,
    existing_file_id: str | None = None,
) -> bool:
    """Upload or update a file in Google Drive.

    If existing_file_id is provided, updates the file content.
    Otherwise creates a new file in the specified folder.
    """
    file_content = await asyncio.to_thread(file_path.read_bytes)

    if existing_file_id:
        # Update existing file content
        response = await _drive_request(
            "PATCH",
            f"{_DRIVE_UPLOAD_BASE}/files/{existing_file_id}",
            token,
            options=DriveRequestOptions(
                content=file_content,
                params={"uploadType": "media"},
                headers={"Content-Type": "application/x-sqlite3"},
            ),
        )
    else:
        # Create new file with multipart upload (metadata + content)

        metadata = json.dumps(
            {
                "name": file_path.name,
                "parents": [folder_id],
            }
        )

        # Use simple two-part upload
        boundary = "wet_mcp_upload_boundary"
        body = (
            (
                f"--{boundary}\r\n"
                f"Content-Type: application/json; charset=UTF-8\r\n\r\n"
                f"{metadata}\r\n"
                f"--{boundary}\r\n"
                f"Content-Type: application/x-sqlite3\r\n\r\n"
            ).encode()
            + file_content
            + f"\r\n--{boundary}--".encode()
        )

        response = await _drive_request(
            "POST",
            f"{_DRIVE_UPLOAD_BASE}/files",
            token,
            options=DriveRequestOptions(
                content=body,
                params={"uploadType": "multipart", "fields": "id"},
                headers={
                    "Content-Type": f"multipart/related; boundary={boundary}",
                },
            ),
        )

    if response.status_code in (200, 201):
        return True

    logger.error(f"Upload failed ({response.status_code}): {response.text[:300]}")
    return False


async def _download_file(token: dict, file_id: str, dest_path: Path) -> bool:
    """Download a file from Google Drive to a local path."""
    response = await _drive_request(
        "GET",
        f"{_DRIVE_API_BASE}/files/{file_id}",
        token,
        options=DriveRequestOptions(
            params={"alt": "media"},
            timeout=300.0,
        ),
    )

    if response.status_code == 200:
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(dest_path.write_bytes, response.content)
        return True

    logger.error(f"Download failed ({response.status_code}): {response.text[:300]}")
    return False


# ---------------------------------------------------------------------------
# Public sync operations
# ---------------------------------------------------------------------------


async def sync_push(db_path: Path, folder_name: str) -> bool:
    """Push local database to Google Drive folder.

    Uploads the SQLite database file to Google Drive.
    Updates existing file or creates new one.
    """
    token = await _get_valid_token()
    if not token:
        logger.error("No valid token for push")
        return False

    logger.info(f"Pushing {db_path.name} to Google Drive/{folder_name}...")

    folder_id = await _find_or_create_folder(token, folder_name)
    if not folder_id:
        logger.error("Failed to find/create sync folder")
        return False

    existing = await _find_file_in_folder(token, folder_id, db_path.name)
    existing_id = existing["id"] if existing else None

    success = await _upload_file(token, db_path, folder_id, existing_id)
    if success:
        logger.info(f"Push complete: {db_path.name} -> Google Drive/{folder_name}")
    else:
        logger.error("Push failed")

    return success


async def sync_pull(db_path: Path, folder_name: str) -> Path | None:
    """Pull remote database from Google Drive to local temp directory.

    Downloads the remote DB file to a temp location for merging.
    Returns path to downloaded file, or None on failure.
    """
    token = await _get_valid_token()
    if not token:
        logger.error("No valid token for pull")
        return None

    logger.info(f"Pulling from Google Drive/{folder_name}...")

    folder_id = await _find_or_create_folder(token, folder_name)
    if not folder_id:
        logger.warning("Sync folder not found")
        return None

    remote_file = await _find_file_in_folder(token, folder_id, db_path.name)
    if not remote_file:
        logger.info("No remote DB file found")
        return None

    temp_dir = db_path.parent / "sync_temp"
    temp_dir.mkdir(parents=True, exist_ok=True)
    temp_db = temp_dir / f"remote_{db_path.name}"

    success = await _download_file(token, remote_file["id"], temp_db)
    if success and temp_db.exists():
        logger.info(f"Pull complete: Google Drive/{folder_name} -> {temp_db}")
        return temp_db

    logger.warning("Pull failed or downloaded file missing")
    temp_db.unlink(missing_ok=True)
    return None


async def sync_full(db: DocsDB) -> dict:
    """Full sync cycle: pull -> merge -> push.

    Returns:
        Dict with sync results.
    """
    from wet_mcp.db import DocsDB

    if not settings.sync_enabled:
        return {"status": "disabled", "message": "Sync not configured"}

    if not settings.google_drive_client_id:
        return {
            "status": "error",
            "message": "GOOGLE_DRIVE_CLIENT_ID not configured",
        }

    # Check for valid token
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

    db_path = settings.get_db_path()
    folder = settings.sync_folder

    result: dict = {"status": "ok", "pull": None, "push": None}

    # 1. Pull remote DB
    remote_db_path = await sync_pull(db_path, folder)
    if remote_db_path:
        try:
            # Open remote DB and export JSONL
            remote_db = DocsDB(remote_db_path, embedding_dims=0)
            remote_jsonl = remote_db.export_jsonl()
            remote_db.close()

            # Import into local DB (merge mode - skip existing)
            if remote_jsonl.strip():
                import_result = db.import_jsonl(remote_jsonl, mode="merge")
                result["pull"] = import_result
                logger.info(f"Merged remote docs: {import_result}")
            else:
                result["pull"] = {
                    "libraries": 0,
                    "versions": 0,
                    "chunks": 0,
                    "skipped": 0,
                }

        except Exception as e:
            logger.error(f"Merge failed: {e}")
            result["pull"] = {"error": str(e)}
        finally:
            # Cleanup temp file
            remote_db_path.unlink(missing_ok=True)
            try:
                remote_db_path.parent.rmdir()
            except OSError:
                pass
    else:
        result["pull"] = {
            "libraries": 0,
            "versions": 0,
            "chunks": 0,
            "skipped": 0,
            "note": "No remote DB found",
        }

    # 2. Push local DB to remote
    push_ok = await sync_push(db_path, folder)
    result["push"] = {"success": push_ok}

    return result


async def check_health() -> bool:
    """Verify Google Drive access by listing files."""
    token = await _get_valid_token()
    if not token:
        return False

    try:
        response = await _drive_request(
            "GET",
            f"{_DRIVE_API_BASE}/files",
            token,
            options=DriveRequestOptions(params={"pageSize": 1, "fields": "files(id)"}),
        )
        return response.status_code == 200
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Device Code OAuth flow
# ---------------------------------------------------------------------------


async def setup_google_auth(
    relay_url: str | None = None,
    session_id: str | None = None,
) -> bool:
    """Interactive Google OAuth setup via Device Code flow.

    If relay_url + session_id provided, send device code via relay messaging.
    Otherwise print to stderr.

    Returns True on success, False on failure.
    """
    import sys

    client_id = settings.google_drive_client_id
    client_secret = settings.google_drive_client_secret
    if not client_id or not client_secret:
        logger.error("GOOGLE_DRIVE_CLIENT_ID or CLIENT_SECRET not configured")
        return False

    # 1. Request device code
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                _DEVICE_CODE_URL,
                data={
                    "client_id": client_id,
                    "scope": _SCOPE,
                },
                timeout=30.0,
            )

            if response.status_code != 200:
                logger.error(f"Device code request failed: {response.text}")
                return False

            device_data = response.json()

    except Exception as e:
        logger.error(f"Device code request error: {e}")
        return False

    device_code = device_data["device_code"]
    user_code = device_data["user_code"]
    verification_url = device_data["verification_url"]
    interval = device_data.get("interval", 5)
    expires_in = device_data.get("expires_in", 1800)

    # 2. Present code to user
    auth_message = (
        f"Google Drive Authorization\n"
        f"Visit: {verification_url}\n"
        f"Enter code: {user_code}"
    )

    if relay_url and session_id:
        # Send via relay messaging
        try:
            async with httpx.AsyncClient() as client:
                await client.post(
                    f"{relay_url}/api/sessions/{session_id}/messages",
                    json={
                        "type": "oauth_device_code",
                        "text": auth_message,
                        "data": {
                            "verification_url": verification_url,
                            "user_code": user_code,
                        },
                    },
                )
        except Exception as e:
            logger.warning(f"Failed to send code via relay: {e}")
    else:
        print(f"\n{auth_message}\n", file=sys.stderr, flush=True)

    # 3. Poll for token
    deadline = time.time() + expires_in

    while time.time() < deadline:
        await asyncio.sleep(interval)

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    _TOKEN_URL,
                    data={
                        "client_id": client_id,
                        "client_secret": client_secret,
                        "device_code": device_code,
                        "grant_type": _DEVICE_CODE_GRANT,
                    },
                    timeout=30.0,
                )

                data = response.json()

                if response.status_code == 200:
                    # Success -- save token
                    token = {
                        "access_token": data["access_token"],
                        "refresh_token": data.get("refresh_token", ""),
                        "expiry": time.time() + data.get("expires_in", 3600),
                        "client_id": client_id,
                        "token_type": data.get("token_type", "Bearer"),
                    }
                    _save_token(token)
                    logger.info("Google Drive authentication successful!")
                    return True

                error = data.get("error", "")
                if error == "authorization_pending":
                    continue
                elif error == "slow_down":
                    interval += 1
                    continue
                elif error in ("access_denied", "expired_token"):
                    logger.error(f"Auth failed: {error}")
                    return False
                else:
                    logger.error(f"Unexpected error: {data}")
                    return False

        except Exception as e:
            logger.error(f"Token poll error: {e}")
            return False

    logger.error("Device code expired")
    return False


# ---------------------------------------------------------------------------
# Auto-sync loop
# ---------------------------------------------------------------------------


async def _auto_sync_loop(db: DocsDB) -> None:
    """Background auto-sync loop."""
    interval = settings.sync_interval
    if interval <= 0:
        return

    logger.info(f"Auto-sync started (interval={interval}s)")
    # Run first sync immediately (don't wait for interval)
    try:
        await sync_full(db)
    except asyncio.CancelledError:
        logger.info("Auto-sync stopped")
        return
    except Exception as e:
        logger.error(f"Initial sync error: {e}")

    while True:
        try:
            await asyncio.sleep(interval)
            await sync_full(db)
        except asyncio.CancelledError:
            logger.info("Auto-sync stopped")
            break
        except Exception as e:
            logger.error(f"Auto-sync error: {e}")
            # Continue running despite errors


def start_auto_sync(db: DocsDB) -> None:
    """Start background auto-sync task."""
    global _sync_task

    if not settings.sync_enabled or settings.sync_interval <= 0:
        return

    if _sync_task and not _sync_task.done():
        return  # Already running

    _sync_task = asyncio.create_task(_auto_sync_loop(db))


def stop_auto_sync() -> None:
    """Stop background auto-sync task."""
    global _sync_task
    if _sync_task and not _sync_task.done():
        _sync_task.cancel()
        _sync_task = None


# ---------------------------------------------------------------------------
# CLI setup entry point
# ---------------------------------------------------------------------------


def setup_sync() -> None:
    """Set up Google Drive sync interactively.

    Usage: wet-mcp setup-sync
    Runs Device Code OAuth flow, saves token locally.
    """
    import sys

    print("=== WET MCP: Setup Google Drive Sync ===")

    client_id = settings.google_drive_client_id
    if not client_id:
        print(
            "ERROR: GOOGLE_DRIVE_CLIENT_ID not set.\n"
            "Create an OAuth client ID at:\n"
            "  https://console.cloud.google.com/apis/credentials\n"
            "Set GOOGLE_DRIVE_CLIENT_ID in your MCP config.",
            file=sys.stderr,
        )
        sys.exit(1)

    success = asyncio.run(setup_google_auth())
    if success:
        print(f"\n{'=' * 60}")
        print("SUCCESS! Token saved locally.")
        print(f"{'=' * 60}\n")
        print("All you need in your MCP config:")
        print('  "SYNC_ENABLED": "true"')
        print(f'  "GOOGLE_DRIVE_CLIENT_ID": "{client_id}"')
        print("\nThe server will auto-load the token from disk.")
    else:
        print(
            "\nERROR: Authentication failed. Please try again.",
            file=sys.stderr,
        )
        sys.exit(1)
