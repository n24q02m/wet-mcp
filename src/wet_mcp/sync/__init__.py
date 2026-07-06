"""Backend-pluggable sync package (Phase 2 refactor, parity with mnemo-mcp).

This package replaces the single-file ``sync.py`` from Phase 1. It still
exports every public + private symbol the existing call sites + tests
import (so ``from wet_mcp.sync import sync_full`` and
``patch("wet_mcp.sync._refresh_token", ...)`` keep working) while also
exposing a backend registry so the Phase 2 docs-sync orchestrator can
choose between Google Drive and S3 (and any future backend) uniformly.

Layout:

* :mod:`wet_mcp.sync.base` - :class:`SyncBackend` abstract contract.
* :mod:`wet_mcp.sync.gdrive` - legacy DB-file sync helpers + new
  :class:`GDriveBackend` adapter for the docs.db sync orchestrator.
* :mod:`wet_mcp.sync.s3` - S3 / R2 / B2 / MinIO backend for operator
  deploy mode (HTTP / Docker), gated on ``SYNC_S3_BUCKET``.

To preserve the Phase 1 monkeypatching pattern (``patch("wet_mcp.sync.X")``)
this ``__init__`` mirrors the gdrive submodule's ``__dict__`` into its own
namespace AND wires the gdrive module's globals so a patch on either
namespace propagates to the actual call site. Tests written against the
single-file ``sync.py`` continue to pass without modification.

Backend selection (XOR semantics):

* No ``SYNC_S3_BUCKET`` env -> :func:`resolve_active_backend` returns
  ``"gdrive"`` and the existing OAuth Device Code flow runs (Method 1,
  uvx local mode).
* ``SYNC_S3_BUCKET`` set -> returns ``"s3"`` and the GDrive flow is
  skipped (operator deploy mode, Method 2 / 3).
"""

from __future__ import annotations

import sys
import types

from wet_mcp.sync import gdrive as _gdrive_module
from wet_mcp.sync.base import SyncBackend
from wet_mcp.sync.gdrive import GDriveBackend

# Mirror every public + private name exported by gdrive.py into this
# package's namespace. Tests that do ``patch("wet_mcp.sync._refresh_token",
# mock)`` set the attribute here; the production code inside gdrive.py looks
# up names in its OWN globals, so we additionally proxy attribute mutations
# from this module into the gdrive module via __setattr__ at the module
# class level (see _SyncModuleProxy below).

_DELEGATE_NAMES = [name for name in dir(_gdrive_module) if not name.startswith("__")]

#: Names representing mutable module-level state inside gdrive.py. We do
#: NOT copy these into the package globals so a fresh ``getattr`` always
#: lands on the live gdrive value (via ``_SyncModuleProxy.__getattr__``).
_LIVE_PROXY_NAMES = {"_sync_task", "_folder_id_cache"}

for _name in _DELEGATE_NAMES:
    if _name in _LIVE_PROXY_NAMES:
        continue
    globals()[_name] = getattr(_gdrive_module, _name)


class _SyncModuleProxy(types.ModuleType):
    """Module subclass that mirrors writes -> gdrive AND reads <- gdrive.

    Tests do ``patch("wet_mcp.sync._foo", mock)`` which calls
    ``sys.modules["wet_mcp.sync"].__setattr__("_foo", mock)``. The patched
    attribute MUST also become visible inside ``gdrive.py``'s globals so the
    function calls there resolve to the mock. Conversely, tests assert
    ``wet_mcp.sync._sync_task == ...`` AFTER ``start_auto_sync`` mutated
    the gdrive global; we mirror reads back so the assertion sees the live
    gdrive value.
    """

    def __setattr__(self, name: str, value: object) -> None:
        if name in _LIVE_PROXY_NAMES:
            # Live state -> only mutate gdrive globals so subsequent
            # ``getattr`` falls through to the live value via __getattr__.
            setattr(_gdrive_module, name, value)
            return
        super().__setattr__(name, value)
        if name in _DELEGATE_NAMES:
            setattr(_gdrive_module, name, value)

    def __getattr__(self, name: str) -> object:
        if name in _DELEGATE_NAMES or hasattr(_gdrive_module, name):
            return getattr(_gdrive_module, name)
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


sys.modules[__name__].__class__ = _SyncModuleProxy


# ---------------------------------------------------------------------------
# Backend registry (Phase 2 NEW)
# ---------------------------------------------------------------------------

_REGISTRY: dict[str, SyncBackend] = {}


def register(name: str, backend: SyncBackend) -> None:
    """Register ``backend`` under ``name`` so :func:`get` can resolve it."""
    if not isinstance(backend, SyncBackend):
        raise TypeError(
            f"register: expected SyncBackend instance, got {type(backend).__name__}"
        )
    _REGISTRY[name] = backend


def get(name: str) -> SyncBackend:
    """Return the registered backend for ``name`` or raise ``KeyError``.

    Lazily registers default backends on first lookup so importing the
    package does not immediately touch httpx / boto3 / OAuth state:

    * ``"gdrive"`` -> :class:`GDriveBackend` (uses Phase 1 OAuth token).
    * ``"s3"`` -> :class:`S3Backend` configured from ``settings.sync_s3_*``.
      Raises ``KeyError`` if ``SYNC_S3_BUCKET`` is unset (so the caller
      sees a helpful "configure SYNC_S3_BUCKET" message instead of a
      cryptic boto3 NoCredentialsError later).
    """
    if name == "gdrive" and "gdrive" not in _REGISTRY:
        _REGISTRY["gdrive"] = GDriveBackend()
    if name == "s3" and "s3" not in _REGISTRY:
        from wet_mcp.config import settings
        from wet_mcp.sync.s3 import S3Backend

        if not settings.sync_s3_bucket:
            raise KeyError(
                "Cannot get('s3'): SYNC_S3_BUCKET is empty. Set the bucket "
                "name (and SYNC_S3_REGION / SYNC_S3_ENDPOINT for R2 / B2 / "
                "MinIO) before requesting the S3 backend."
            )
        _REGISTRY["s3"] = S3Backend(
            bucket=settings.sync_s3_bucket,
            region=settings.sync_s3_region or "us-east-1",
            access_key_id=settings.sync_s3_access_key_id or None,
            secret_access_key=settings.sync_s3_secret_access_key or None,
            endpoint_url=settings.sync_s3_endpoint or None,
            prefix=settings.sync_s3_prefix or "docs/",
        )
    if name not in _REGISTRY:
        raise KeyError(
            f"Unknown sync backend {name!r}; "
            f"registered backends: {sorted(_REGISTRY.keys())}"
        )
    return _REGISTRY[name]


def list_backends() -> list[str]:
    """Return the list of registered backend names sorted alphabetically."""
    return sorted(_REGISTRY.keys())


def reset_registry() -> None:
    """Clear the registry (test helper - do not call in production)."""
    _REGISTRY.clear()


def resolve_active_backend() -> str:
    """Resolve the active sync backend name from environment.

    Returns ``"s3"`` when ``SYNC_S3_BUCKET`` is non-empty (operator deploy
    mode: HTTP / Docker), otherwise ``"gdrive"`` (default uvx Method 1
    local-relay mode with per-user OAuth Device Code).

    The two backends are mutually exclusive at deployment level - a single
    process never runs both. Callers should treat this as the single
    source of truth and gate Google Drive setup / S3 client init behind
    this resolver.
    """
    from wet_mcp.config import settings

    if settings.sync_s3_bucket:
        return "s3"
    return "gdrive"


# ---------------------------------------------------------------------------
# S3 auto-sync loop (operator deploy mode)
# ---------------------------------------------------------------------------

import asyncio  # noqa: E402

_s3_sync_task: asyncio.Task | None = None


async def _s3_auto_sync_loop(db) -> None:  # type: ignore[no-untyped-def]
    """Background loop pushing docs.db to S3 every ``SYNC_INTERVAL`` seconds.

    On startup we attempt a pull first (so a fresh container hydrates
    from the bucket). Subsequent ticks push the local docs.db; pulls
    are only useful at startup since the bucket has overwrite-on-push
    semantics and the container is the canonical writer.
    """
    from loguru import logger

    from wet_mcp.config import settings as _settings

    interval = _settings.sync_interval
    if interval <= 0:
        logger.info("S3 auto-sync disabled (SYNC_INTERVAL <= 0)")
        return

    try:
        backend = get("s3")
    except KeyError as e:
        logger.error(f"S3 auto-sync init failed: {e}")
        return

    db_path = _settings.get_db_path()
    logger.info(f"S3 auto-sync started (interval={interval}s)")

    # 1. Initial pull: hydrate fresh container from bucket if remote
    #    has a docs.db. We do NOT overwrite local on pull - the merge
    #    happens via JSONL import like the GDrive path (see sync_full).
    try:
        remote_db_path = await backend.pull(db_path)
        if remote_db_path:
            logger.info(f"S3 hydrate: remote docs.db downloaded -> {remote_db_path}")
            try:
                from wet_mcp.db import DocsDB

                remote_db = DocsDB(remote_db_path, embedding_dims=0)
                remote_jsonl = remote_db.export_jsonl()
                remote_db.close()
                if remote_jsonl.strip():
                    result = db.import_jsonl(remote_jsonl, mode="merge")
                    logger.info(f"S3 hydrate merge ok: {result}")
            except Exception as e:
                logger.warning(f"S3 hydrate merge failed (non-fatal): {e}")
            finally:
                remote_db_path.unlink(missing_ok=True)
                try:
                    remote_db_path.parent.rmdir()
                except OSError:
                    pass
    except asyncio.CancelledError:
        logger.info("S3 auto-sync stopped during hydrate")
        return
    except Exception as e:
        logger.warning(f"S3 hydrate failed (non-fatal): {e}")

    # 2. Push loop: every interval, upload local docs.db.
    while True:
        try:
            await asyncio.sleep(interval)
            await backend.push(db_path)
        except asyncio.CancelledError:
            logger.info("S3 auto-sync stopped")
            return
        except Exception as e:
            logger.error(f"S3 auto-sync push error (non-fatal): {e}")


def start_s3_auto_sync(db) -> None:  # type: ignore[no-untyped-def]
    """Start background S3 auto-sync task.

    Idempotent: returns early when SYNC_S3_BUCKET is unset, when the
    interval is <= 0, or when a task is already running.
    """
    global _s3_sync_task
    from wet_mcp.config import settings as _settings

    if not _settings.sync_s3_bucket:
        return
    if _settings.sync_interval <= 0:
        return
    if _s3_sync_task is not None and not _s3_sync_task.done():
        return

    try:
        _s3_sync_task = asyncio.create_task(_s3_auto_sync_loop(db))
    except RuntimeError:
        # No running event loop (e.g. in test harness). Caller can
        # schedule manually if needed.
        pass


def stop_s3_auto_sync() -> None:
    """Cancel the background S3 auto-sync task if running."""
    global _s3_sync_task
    if _s3_sync_task is not None and not _s3_sync_task.done():
        _s3_sync_task.cancel()
    _s3_sync_task = None
