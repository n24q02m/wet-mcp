"""Tests for the SyncBackend base class."""

from pathlib import Path

import pytest

from wet_mcp.sync.base import SyncBackend


class DummyBackend(SyncBackend):
    """A concrete implementation of SyncBackend for testing."""

    name = "dummy"

    async def push(self, db_path: Path) -> bool:
        return True

    async def pull(self, db_path: Path) -> Path | None:
        return db_path

    async def health_check(self) -> bool:
        return True

    @property
    def supports_oauth_setup(self) -> bool:
        return False


def test_sync_backend_is_abstract():
    """Verify that SyncBackend cannot be instantiated directly."""
    with pytest.raises(TypeError, match="Can't instantiate abstract class SyncBackend"):
        SyncBackend()  # type: ignore


@pytest.mark.asyncio
async def test_dummy_backend_instantiation():
    """Verify that a concrete implementation of SyncBackend can be instantiated."""
    backend = DummyBackend()
    assert backend.name == "dummy"
    assert await backend.push(Path("test.db")) is True
    assert await backend.pull(Path("test.db")) == Path("test.db")
    assert await backend.health_check() is True
    assert backend.supports_oauth_setup is False


def test_dummy_backend_defaults():
    """Verify default name of SyncBackend (empty string)."""

    class DefaultNameBackend(SyncBackend):
        async def push(self, db_path: Path) -> bool:
            return True

        async def pull(self, db_path: Path) -> Path | None:
            return db_path

        async def health_check(self) -> bool:
            return True

        @property
        def supports_oauth_setup(self) -> bool:
            return False

    backend = DefaultNameBackend()
    assert backend.name == ""
