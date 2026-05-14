"""S3-compatible docs-sync backend (Phase 2, parity with mnemo-mcp).

Implements :class:`SyncBackend` against any S3-compatible object store
(AWS S3, Cloudflare R2, Backblaze B2, MinIO, etc.) via boto3. wet-mcp's
docs.db is uploaded directly to ``<prefix>/docs.db`` with overwrite-on-
push semantics - simpler than mnemo-mcp's bundle-with-sequence pattern
because docs.db is a non-sensitive cache of indexed open-source docs
(no per-update encryption / monotonic versioning required).

Wiring:

* Settings live in :mod:`wet_mcp.config` (``SYNC_S3_*`` env vars).
* When ``SYNC_S3_BUCKET`` is non-empty + creds resolve, the package
  registers an ``S3Backend`` instance under name ``"s3"`` so callers
  can ``sync.get("s3")`` via :func:`wet_mcp.sync.resolve_active_backend`.
* Custom ``endpoint_url`` lets the backend talk to R2 / B2 / MinIO -
  AWS-S3 callers leave it unset so boto3 picks the regional default.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import boto3
from botocore.exceptions import ClientError
from loguru import logger

from wet_mcp.sync.base import SyncBackend

# docs.db is uploaded at ``<prefix>/docs.db`` with overwrite-on-push
# semantics. Unlike mnemo-mcp's passport bundles (which use monotonic
# ``seq-NNNNNN.bin`` keys for delta sync), the wet docs cache is
# idempotent + last-write-wins - re-indexing the same library produces
# the same chunks, so a flat single-file layout is sufficient.
_DOCS_DB_FILENAME = "docs.db"


def _docs_key(prefix: str) -> str:
    """Return the S3 object key for the docs.db file."""
    return f"{prefix.rstrip('/')}/{_DOCS_DB_FILENAME}"


class S3Backend(SyncBackend):
    """:class:`SyncBackend` over a generic S3 / R2 / B2 / MinIO bucket.

    The bucket is treated as a flat key/value store rooted at
    ``<prefix>/`` (default ``docs/``). Each push overwrites
    ``<prefix>/docs.db``; each pull downloads the current object to a
    caller-supplied temp path.
    """

    name = "s3"

    def __init__(
        self,
        bucket: str,
        region: str = "us-east-1",
        access_key_id: str | None = None,
        secret_access_key: str | None = None,
        endpoint_url: str | None = None,
        prefix: str = "docs/",
    ) -> None:
        self._bucket = bucket
        self._prefix = prefix.rstrip("/") + "/"
        self._endpoint_url = endpoint_url
        self._client = boto3.client(
            "s3",
            region_name=region,
            endpoint_url=endpoint_url,
            aws_access_key_id=access_key_id,
            aws_secret_access_key=secret_access_key,
        )

    async def push(self, db_path: Path) -> bool:
        """Upload ``db_path`` to ``<prefix>/docs.db`` (overwrite)."""
        key = _docs_key(self._prefix)
        try:
            body = await asyncio.to_thread(db_path.read_bytes)
            await asyncio.to_thread(
                self._client.put_object,
                Bucket=self._bucket,
                Key=key,
                Body=body,
            )
            logger.info(f"S3 push ok bucket={self._bucket} key={key} bytes={len(body)}")
            return True
        except ClientError as e:
            logger.error(f"S3 push failed bucket={self._bucket} key={key} err={e}")
            return False
        except OSError as e:
            logger.error(f"S3 push read failed db_path={db_path} err={e}")
            return False

    async def pull(self, db_path: Path) -> Path | None:
        """Download ``<prefix>/docs.db`` to a temp path next to ``db_path``.

        Returns the temp path on success, or ``None`` when the remote
        has no docs.db yet (fresh backend state) or download failed.
        """
        key = _docs_key(self._prefix)
        try:
            resp = await asyncio.to_thread(
                self._client.get_object, Bucket=self._bucket, Key=key
            )
            content = await asyncio.to_thread(resp["Body"].read)
        except ClientError as e:
            code = e.response.get("Error", {}).get("Code", "")
            if code in ("NoSuchKey", "404"):
                logger.info(f"S3 pull: no remote docs.db yet bucket={self._bucket}")
                return None
            logger.error(f"S3 pull failed bucket={self._bucket} key={key} err={e}")
            return None

        temp_dir = db_path.parent / "sync_temp"
        temp_dir.mkdir(parents=True, exist_ok=True)
        temp_db = temp_dir / f"remote_{db_path.name}"
        await asyncio.to_thread(temp_db.write_bytes, content)
        logger.info(
            f"S3 pull ok bucket={self._bucket} key={key} bytes={len(content)} "
            f"-> {temp_db}"
        )
        return temp_db

    async def health_check(self) -> bool:
        """Cheap probe: HeadBucket. Returns False on 403 / 404 / network."""
        try:
            await asyncio.to_thread(self._client.head_bucket, Bucket=self._bucket)
            return True
        except ClientError:
            return False
        except Exception:
            return False

    @property
    def supports_oauth_setup(self) -> bool:
        """S3 uses operator-provisioned static credentials, no OAuth flow."""
        return False
