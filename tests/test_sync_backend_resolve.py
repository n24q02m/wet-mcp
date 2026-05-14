"""Tests for the Phase 2 sync backend registry + resolver.

Mirrors mnemo-mcp/tests/sync/test_backend_registry.py - covers:
- :func:`register` accepts SyncBackend instances and rejects others.
- :func:`get` returns the registered backend or raises KeyError with a
  helpful message listing the registered names.
- :func:`get("gdrive")` lazily registers :class:`GDriveBackend` on first call.
- :class:`GDriveBackend` is a :class:`SyncBackend` subclass and exposes
  the four-method contract.
- :func:`resolve_active_backend` returns ``"s3"`` when SYNC_S3_BUCKET set,
  ``"gdrive"`` otherwise.
- Legacy ``from wet_mcp.sync import sync_full`` imports still work.
- ``patch("wet_mcp.sync._refresh_token", ...)`` propagates to gdrive globals.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import cast

import pytest

from wet_mcp import sync as sync_pkg
from wet_mcp.sync import (
    GDriveBackend,
    SyncBackend,
    get,
    list_backends,
    register,
    reset_registry,
    resolve_active_backend,
)


@pytest.fixture(autouse=True)
def _isolated_registry() -> Iterator[None]:
    reset_registry()
    yield
    reset_registry()


class _Mock(SyncBackend):
    name = "mock"

    async def push(self, db_path):  # noqa: ARG002
        return True

    async def pull(self, db_path):  # noqa: ARG002
        return None

    async def health_check(self) -> bool:
        return True

    @property
    def supports_oauth_setup(self) -> bool:
        return False


def test_register_accepts_sync_backend_instance() -> None:
    backend = _Mock()
    register("mock", backend)
    assert get("mock") is backend


def test_register_rejects_non_sync_backend() -> None:
    with pytest.raises(TypeError, match="SyncBackend instance"):
        register("bad", cast(SyncBackend, "not-a-backend"))


def test_get_unknown_backend_raises_keyerror_listing_names() -> None:
    register("mock", _Mock())
    with pytest.raises(KeyError) as exc:
        get("does-not-exist")
    assert "does-not-exist" in str(exc.value)
    assert "mock" in str(exc.value)


def test_get_gdrive_lazy_registers() -> None:
    assert "gdrive" not in list_backends()
    backend = get("gdrive")
    assert isinstance(backend, GDriveBackend)
    assert "gdrive" in list_backends()
    # Second call returns the same instance.
    assert get("gdrive") is backend


def test_gdrive_backend_subclasses_sync_backend() -> None:
    assert issubclass(GDriveBackend, SyncBackend)
    inst = GDriveBackend()
    # Four contract methods are present and async-callable signatures.
    assert callable(inst.push)
    assert callable(inst.pull)
    assert callable(inst.health_check)
    assert inst.supports_oauth_setup is True


def test_list_backends_returns_sorted_names() -> None:
    register("zeta", _Mock())
    register("alpha", _Mock())
    assert list_backends() == ["alpha", "zeta"]


def test_legacy_function_imports_still_work() -> None:
    """Phase 1 callers do ``from wet_mcp.sync import sync_full`` etc.

    Confirm those names remain importable AND callable post-refactor.
    """
    from wet_mcp.sync import (  # noqa: F401 - import is the test
        check_health,
        setup_google_auth,
        start_auto_sync,
        stop_auto_sync,
        sync_full,
        sync_pull,
        sync_push,
    )

    assert callable(sync_full)
    assert callable(setup_google_auth)
    assert callable(check_health)


def test_sync_module_setattr_propagates_to_gdrive(monkeypatch) -> None:
    """``patch("wet_mcp.sync._refresh_token", mock)`` MUST also be the
    name resolved inside ``gdrive.py`` so the production code call hits
    the mock instead of the original function.
    """
    from wet_mcp.sync import gdrive

    sentinel = object()
    monkeypatch.setattr("wet_mcp.sync._refresh_token", sentinel)
    assert gdrive._refresh_token is sentinel

    # Cleanup is automatic via monkeypatch.
    assert sync_pkg._refresh_token is sentinel


# ---------------------------------------------------------------------------
# resolve_active_backend
# ---------------------------------------------------------------------------


def test_resolve_active_backend_no_env_returns_gdrive(monkeypatch) -> None:
    """Default (no SYNC_S3_BUCKET) -> gdrive mode for Method 1 uvx."""
    monkeypatch.setattr("wet_mcp.config.settings.sync_s3_bucket", "")
    assert resolve_active_backend() == "gdrive"


def test_resolve_active_backend_s3_env_returns_s3(monkeypatch) -> None:
    """SYNC_S3_BUCKET set -> s3 mode for Method 2/3 Docker operator deploy."""
    monkeypatch.setattr("wet_mcp.config.settings.sync_s3_bucket", "my-bucket")
    assert resolve_active_backend() == "s3"


def test_get_s3_raises_when_bucket_unset(monkeypatch) -> None:
    """``get("s3")`` MUST refuse to construct a backend without bucket name."""
    monkeypatch.setattr("wet_mcp.config.settings.sync_s3_bucket", "")
    with pytest.raises(KeyError, match="SYNC_S3_BUCKET is empty"):
        get("s3")


def test_get_s3_lazy_registers_when_bucket_set(monkeypatch) -> None:
    """``get("s3")`` constructs S3Backend from settings on first call."""
    monkeypatch.setattr("wet_mcp.config.settings.sync_s3_bucket", "test-bucket")
    monkeypatch.setattr("wet_mcp.config.settings.sync_s3_region", "us-east-1")
    monkeypatch.setattr("wet_mcp.config.settings.sync_s3_access_key_id", "k")
    monkeypatch.setattr("wet_mcp.config.settings.sync_s3_secret_access_key", "s")
    monkeypatch.setattr("wet_mcp.config.settings.sync_s3_endpoint", "")
    monkeypatch.setattr("wet_mcp.config.settings.sync_s3_prefix", "docs/")

    from wet_mcp.sync.s3 import S3Backend

    backend = get("s3")
    assert isinstance(backend, S3Backend)
    # Second call returns same instance.
    assert get("s3") is backend


# ---------------------------------------------------------------------------
# start_s3_auto_sync / stop_s3_auto_sync lifecycle
# ---------------------------------------------------------------------------


def test_start_s3_auto_sync_noop_when_no_bucket(monkeypatch) -> None:
    """No SYNC_S3_BUCKET -> start_s3_auto_sync returns without scheduling."""
    from wet_mcp.sync import start_s3_auto_sync, stop_s3_auto_sync

    monkeypatch.setattr("wet_mcp.config.settings.sync_s3_bucket", "")
    # Should not raise / hang regardless of event-loop state.
    start_s3_auto_sync(db=None)
    stop_s3_auto_sync()


def test_start_s3_auto_sync_noop_when_interval_zero(monkeypatch) -> None:
    """SYNC_INTERVAL <= 0 disables the loop even when bucket is set."""
    from wet_mcp.sync import start_s3_auto_sync, stop_s3_auto_sync

    monkeypatch.setattr("wet_mcp.config.settings.sync_s3_bucket", "b")
    monkeypatch.setattr("wet_mcp.config.settings.sync_interval", 0)
    start_s3_auto_sync(db=None)
    stop_s3_auto_sync()


def test_stop_s3_auto_sync_idempotent() -> None:
    """``stop_s3_auto_sync`` is safe to call when nothing is running."""
    from wet_mcp.sync import stop_s3_auto_sync

    stop_s3_auto_sync()
    stop_s3_auto_sync()  # second call must not raise


# ---------------------------------------------------------------------------
# _s3_auto_sync_loop end-to-end
# ---------------------------------------------------------------------------


async def test_s3_auto_sync_loop_interval_zero_returns_early(monkeypatch) -> None:
    """SYNC_INTERVAL <= 0 -> loop exits without scheduling."""
    from wet_mcp.sync import _s3_auto_sync_loop

    monkeypatch.setattr("wet_mcp.config.settings.sync_interval", 0)
    monkeypatch.setattr("wet_mcp.config.settings.sync_s3_bucket", "b")
    # Returns without exception even though db is None / no backend.
    await _s3_auto_sync_loop(db=None)


async def test_s3_auto_sync_loop_backend_init_failure(monkeypatch) -> None:
    """``get("s3")`` KeyError -> logged + early return."""
    from wet_mcp.sync import _s3_auto_sync_loop

    monkeypatch.setattr("wet_mcp.config.settings.sync_interval", 1)
    monkeypatch.setattr("wet_mcp.config.settings.sync_s3_bucket", "")  # forces KeyError
    await _s3_auto_sync_loop(db=None)


async def test_s3_auto_sync_loop_hydrate_and_push(monkeypatch, tmp_path) -> None:
    """Full loop: hydrate (no remote) -> push -> cancel."""
    import asyncio as _asyncio
    from unittest.mock import AsyncMock, MagicMock

    from wet_mcp.sync import _s3_auto_sync_loop

    monkeypatch.setattr("wet_mcp.config.settings.sync_interval", 0.05)
    monkeypatch.setattr("wet_mcp.config.settings.sync_s3_bucket", "b")
    monkeypatch.setattr(
        type(__import__("wet_mcp.config", fromlist=["settings"]).settings),
        "get_db_path",
        lambda self: tmp_path / "docs.db",
    )

    fake_backend = MagicMock()
    fake_backend.pull = AsyncMock(return_value=None)
    fake_backend.push = AsyncMock(return_value=True)

    monkeypatch.setattr("wet_mcp.sync.get", lambda name: fake_backend)

    task = _asyncio.create_task(_s3_auto_sync_loop(db=MagicMock()))
    await _asyncio.sleep(0.15)  # allow at least one push tick
    task.cancel()
    try:
        await task
    except _asyncio.CancelledError:
        pass

    assert fake_backend.pull.await_count >= 1
    assert fake_backend.push.await_count >= 1


async def test_s3_auto_sync_loop_push_error_is_non_fatal(monkeypatch, tmp_path) -> None:
    """A push raising an exception is logged but the loop keeps running."""
    import asyncio as _asyncio
    from unittest.mock import AsyncMock, MagicMock

    from wet_mcp.sync import _s3_auto_sync_loop

    monkeypatch.setattr("wet_mcp.config.settings.sync_interval", 0.05)
    monkeypatch.setattr("wet_mcp.config.settings.sync_s3_bucket", "b")
    monkeypatch.setattr(
        type(__import__("wet_mcp.config", fromlist=["settings"]).settings),
        "get_db_path",
        lambda self: tmp_path / "docs.db",
    )

    fake_backend = MagicMock()
    fake_backend.pull = AsyncMock(return_value=None)
    fake_backend.push = AsyncMock(side_effect=RuntimeError("boom"))

    monkeypatch.setattr("wet_mcp.sync.get", lambda name: fake_backend)

    task = _asyncio.create_task(_s3_auto_sync_loop(db=MagicMock()))
    await _asyncio.sleep(0.2)
    assert fake_backend.push.await_count >= 2  # still ticking after error
    task.cancel()
    try:
        await task
    except _asyncio.CancelledError:
        pass
