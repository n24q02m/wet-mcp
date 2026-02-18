"""Embedded Rclone process management for docs sync.

Syncs the docs database (libraries + chunks) across machines using
rclone. Only docs data is synced — web cache (search/extract) is
ephemeral and not synced.

Sync flow:
1. rclone installed/found -> configured with remote
2. Push: copy local DB to remote folder
3. Pull: copy remote DB to local, merge via JSONL export/import
4. Auto-sync: periodic push/pull in background

Resilience:
- Auto-download rclone binary on first use
- Health check before sync operations
- Conflict resolution via timestamp-based merge
- Configurable sync interval (0 = manual only)
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import platform
import shutil
import stat
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import TYPE_CHECKING

import httpx
from loguru import logger

from wet_mcp.config import settings

if TYPE_CHECKING:
    from wet_mcp.db import DocsDB

# Rclone version to download
_RCLONE_VERSION = "v1.68.2"

# Background sync task reference
_sync_task: asyncio.Task | None = None


def _get_rclone_dir() -> Path:
    """Get directory for rclone binary."""
    return settings.get_data_dir() / "bin"


def _get_rclone_path() -> Path | None:
    """Find rclone binary.

    Priority:
    1. System-installed rclone (in PATH)
    2. Bundled rclone in data dir
    """
    # Check system PATH first
    system_rclone = shutil.which("rclone")
    if system_rclone:
        return Path(system_rclone)

    # Check bundled binary
    ext = ".exe" if sys.platform == "win32" else ""
    bundled = _get_rclone_dir() / f"rclone{ext}"
    if bundled.exists():
        return bundled

    return None


def _get_platform_info() -> tuple[str, str, str]:
    """Get OS, arch, and file extension for rclone download.

    Returns:
        Tuple of (os_name, arch_name, extension).
    """
    system = platform.system().lower()
    machine = platform.machine().lower()

    if system == "windows":
        os_name = "windows"
        ext = ".exe"
    elif system == "darwin":
        os_name = "osx"
        ext = ""
    else:
        os_name = "linux"
        ext = ""

    if machine in ("x86_64", "amd64"):
        arch = "amd64"
    elif machine in ("aarch64", "arm64"):
        arch = "arm64"
    elif machine in ("i386", "i686"):
        arch = "386"
    else:
        arch = "amd64"  # Fallback

    return os_name, arch, ext


async def _download_rclone() -> Path | None:
    """Download rclone binary for current platform.

    Returns path to binary on success, None on failure.
    """
    os_name, arch, ext = _get_platform_info()
    archive_name = f"rclone-{_RCLONE_VERSION}-{os_name}-{arch}.zip"
    url = f"https://github.com/rclone/rclone/releases/download/{_RCLONE_VERSION}/{archive_name}"

    install_dir = _get_rclone_dir()
    install_dir.mkdir(parents=True, exist_ok=True)
    target_path = install_dir / f"rclone{ext}"

    if target_path.exists():
        return target_path

    logger.info(f"Downloading rclone {_RCLONE_VERSION} for {os_name}-{arch}...")

    try:
        async with httpx.AsyncClient(follow_redirects=True) as client:
            response = await client.get(url, timeout=120.0)
            response.raise_for_status()

            # Write to temp file
            with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tmp:
                tmp.write(response.content)
                tmp_path = Path(tmp.name)

        # Extract rclone binary from zip
        with zipfile.ZipFile(tmp_path, "r") as zf:
            # Find rclone binary in archive
            binary_name = f"rclone{ext}"
            for info in zf.infolist():
                if info.filename.endswith(binary_name) and not info.is_dir():
                    # Extract to temp, then move
                    with zf.open(info) as src:
                        target_path.write_bytes(src.read())
                    break
            else:
                logger.error("rclone binary not found in archive")
                return None

        # Make executable on Unix
        if ext == "":
            target_path.chmod(target_path.stat().st_mode | stat.S_IEXEC)

        # Cleanup temp zip
        tmp_path.unlink(missing_ok=True)

        logger.info(f"rclone installed: {target_path}")
        return target_path

    except Exception as e:
        logger.error(f"Failed to download rclone: {e}")
        return None


async def ensure_rclone() -> Path | None:
    """Ensure rclone is available, downloading if needed.

    Returns path to rclone binary, or None if unavailable.
    """
    path = await asyncio.to_thread(_get_rclone_path)
    if path:
        return path

    # Download
    return await _download_rclone()


def _prepare_rclone_env() -> dict[str, str]:
    """Prepare env dict for rclone, decoding base64 tokens if needed.

    Supports both raw JSON and base64-encoded tokens in
    ``RCLONE_CONFIG_*_TOKEN`` env vars.  Base64 avoids nested JSON
    escaping issues in MCP config files.
    """
    env = os.environ.copy()
    for key in list(env):
        if key.startswith("RCLONE_CONFIG_") and key.endswith("_TOKEN"):
            value = env[key]
            if value and not value.lstrip().startswith("{"):
                try:
                    decoded = base64.b64decode(value).decode("utf-8")
                    json.loads(decoded)  # Validate JSON structure
                    env[key] = decoded
                except Exception:
                    pass
    return env


def _run_rclone(
    rclone_path: Path, args: list[str], timeout: int = 120
) -> subprocess.CompletedProcess:
    """Run rclone command synchronously."""
    cmd = [str(rclone_path), *args]
    logger.debug(f"rclone: {' '.join(cmd)}")

    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
        env=_prepare_rclone_env(),
    )


async def check_remote_configured(rclone_path: Path, remote: str) -> bool:
    """Check if an rclone remote is configured."""
    result = await asyncio.to_thread(_run_rclone, rclone_path, ["listremotes"], 10)
    if result.returncode != 0:
        return False

    remotes = [
        r.strip().rstrip(":") for r in result.stdout.strip().split("\n") if r.strip()
    ]
    return remote in remotes


async def sync_push(rclone_path: Path, db_path: Path, remote: str, folder: str) -> bool:
    """Push local database to remote.

    Copies the SQLite database file to the remote folder.
    Uses rclone copy (not sync) to avoid deleting remote files.
    """
    remote_dest = f"{remote}:{folder}"

    logger.info(f"Pushing {db_path.name} to {remote_dest}...")

    result = await asyncio.to_thread(
        _run_rclone,
        rclone_path,
        ["copy", str(db_path), remote_dest, "--progress"],
        300,
    )

    if result.returncode == 0:
        logger.info(f"Push complete: {db_path.name} -> {remote_dest}")
        return True
    else:
        logger.error(f"Push failed: {result.stderr[:300]}")
        return False


async def sync_pull(
    rclone_path: Path, db_path: Path, remote: str, folder: str
) -> Path | None:
    """Pull remote database to local temp directory.

    Downloads the remote DB file to a temp location for merging.
    Returns path to downloaded file, or None on failure.
    """
    remote_src = f"{remote}:{folder}/{db_path.name}"
    temp_dir = db_path.parent / "sync_temp"
    temp_dir.mkdir(parents=True, exist_ok=True)
    temp_db = temp_dir / f"remote_{db_path.name}"

    logger.info(f"Pulling from {remote_src}...")

    result = await asyncio.to_thread(
        _run_rclone,
        rclone_path,
        ["copyto", remote_src, str(temp_db), "--progress"],
        300,
    )

    if result.returncode == 0 and temp_db.exists():
        logger.info(f"Pull complete: {remote_src} -> {temp_db}")
        return temp_db
    else:
        logger.warning(f"Pull failed or no remote file: {result.stderr[:200]}")
        # Cleanup
        temp_db.unlink(missing_ok=True)
        return None


async def sync_full(db: DocsDB) -> dict:
    """Full sync cycle: pull -> merge -> push.

    Returns:
        Dict with sync results.
    """
    from wet_mcp.db import DocsDB

    if not settings.sync_enabled or not settings.sync_remote:
        return {"status": "disabled", "message": "Sync not configured"}

    rclone_path = await ensure_rclone()
    if not rclone_path:
        return {"status": "error", "message": "rclone not available"}

    # Check remote is configured
    if not await check_remote_configured(rclone_path, settings.sync_remote):
        remote_upper = settings.sync_remote.upper()
        return {
            "status": "error",
            "message": f"rclone remote '{settings.sync_remote}' not configured. "
            f"Set RCLONE_CONFIG_{remote_upper}_TYPE and "
            f"RCLONE_CONFIG_{remote_upper}_TOKEN env vars.",
        }

    db_path = settings.get_db_path()
    remote = settings.sync_remote
    folder = settings.sync_folder

    result: dict = {"status": "ok", "pull": None, "push": None}

    # 1. Pull remote DB
    remote_db_path = await sync_pull(rclone_path, db_path, remote, folder)
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
    push_ok = await sync_push(rclone_path, db_path, remote, folder)
    result["push"] = {"success": push_ok}

    return result


async def _auto_sync_loop(db: DocsDB) -> None:
    """Background auto-sync loop."""
    interval = settings.sync_interval
    if interval <= 0:
        return

    logger.info(f"Auto-sync started (interval={interval}s)")
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


def _extract_token(output: str) -> str | None:
    """Extract rclone OAuth token JSON from authorize output.

    rclone outputs the token between dashed lines like:
        Paste the following into your remote machine config
        --------------------
        {"access_token":"...","token_type":"Bearer",...}
        --------------------
    """
    import re

    # Try to find JSON between ---- markers
    pattern = r"-{4,}\s*\n\s*(\{[^}]+\})\s*\n\s*-{4,}"
    match = re.search(pattern, output)
    if match:
        return match.group(1).strip()

    # Fallback: find any JSON object with access_token
    pattern = r'\{"access_token"[^}]+\}'
    match = re.search(pattern, output)
    if match:
        return match.group(0).strip()

    return None


def setup_sync(remote_type: str = "drive") -> None:
    """Download rclone and run authorize to get a token.

    Usage: wet-mcp setup-sync [type]
    Default type: drive (Google Drive)

    Captures the token from rclone output, base64-encodes it,
    and prints ready-to-paste MCP config.
    """

    print(f"=== WET MCP: Setup Sync ({remote_type}) ===\n")

    # 1. Ensure rclone is available
    rclone_path = _get_rclone_path()
    if rclone_path:
        print(f"rclone found: {rclone_path}")
    else:
        print("Downloading rclone...")
        rclone_path = asyncio.run(_download_rclone())
        if not rclone_path:
            print("ERROR: Failed to download rclone", file=sys.stderr)
            sys.exit(1)
        print(f"rclone installed: {rclone_path}")

    # 2. Run rclone authorize (interactive — opens browser)
    print(f'\nRunning: rclone authorize "{remote_type}"')
    print("A browser window will open for authentication.\n")
    print("-" * 50)

    result = subprocess.run(
        [str(rclone_path), "authorize", remote_type],
        stdout=subprocess.PIPE,
        text=True,
        timeout=300,
    )

    print("-" * 50)

    if result.returncode != 0:
        print(
            f"\nERROR: rclone authorize failed (exit {result.returncode})",
            file=sys.stderr,
        )
        sys.exit(1)

    # 3. Extract token JSON from stdout
    token_json = _extract_token(result.stdout or "")

    remote_name = "gdrive" if remote_type == "drive" else remote_type
    remote_upper = remote_name.upper()

    if token_json:
        token_b64 = base64.b64encode(token_json.encode()).decode()

        print(f"\n{'=' * 60}")
        print(f"RCLONE_CONFIG_{remote_upper}_TOKEN (base64-encoded)")
        print(f"{'=' * 60}\n")
        print(token_b64)
        print(f"\n{'=' * 60}")
        print("\nEnv vars needed for sync:")
        print("  SYNC_ENABLED=true")
        print(f"  SYNC_REMOTE={remote_name}")
        print(f"  RCLONE_CONFIG_{remote_upper}_TYPE={remote_type}")
        print(f"  RCLONE_CONFIG_{remote_upper}_TOKEN=<base64 above>")
        print("\nServer auto-decodes base64 at runtime.")
        print("Both raw JSON and base64 tokens are supported.")
    else:
        print(f"\n{'=' * 60}")
        print("MANUAL SETUP")
        print(f"{'=' * 60}\n")
        print("Could not auto-extract token from rclone output.")
        print("Copy the token JSON from above and base64-encode it:\n")
        if sys.platform == "win32":
            print(
                '  python -c "import base64,sys; print(base64.b64encode(input().encode()).decode())"'
            )
        else:
            print(
                "  python3 -c 'import base64,sys; print(base64.b64encode(input().encode()).decode())'"
            )
        print("\nThen set these env vars:")
        print("  SYNC_ENABLED=true")
        print(f"  SYNC_REMOTE={remote_name}")
        print(f"  RCLONE_CONFIG_{remote_upper}_TYPE={remote_type}")
        print(f"  RCLONE_CONFIG_{remote_upper}_TOKEN=<base64 output>")
