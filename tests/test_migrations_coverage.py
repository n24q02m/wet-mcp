from __future__ import annotations

import sqlite3
from pathlib import Path
from unittest.mock import patch

from alembic import command

from wet_mcp.migrations import (
    _backup_db_file,
    _read_alembic_version,
    run_migrations_on_startup,
)


def test_read_alembic_version_no_file(tmp_path: Path) -> None:
    """Line 39: _read_alembic_version returns None if file missing."""
    assert _read_alembic_version(tmp_path / "nope.db") is None


def test_read_alembic_version_empty_table(tmp_path: Path) -> None:
    """Line 47: _read_alembic_version returns None if table exists but is empty."""
    db_path = tmp_path / "empty.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)")
    conn.commit()
    conn.close()
    assert _read_alembic_version(db_path) is None


def test_backup_db_file_no_file(tmp_path: Path) -> None:
    """Line 61: _backup_db_file returns None if source missing."""
    assert _backup_db_file(tmp_path / "nope.db") is None


def test_backup_db_file_with_sidecars(tmp_path: Path) -> None:
    """Line 70: _backup_db_file copies -wal and -shm if they exist."""
    db_path = tmp_path / "docs.db"
    db_path.write_text("main")
    (tmp_path / "docs.db-wal").write_text("wal")
    (tmp_path / "docs.db-shm").write_text("shm")

    backup_path = _backup_db_file(db_path)
    assert backup_path is not None
    assert backup_path.exists()
    assert backup_path.with_suffix(backup_path.suffix + "-wal").exists()
    assert backup_path.with_suffix(backup_path.suffix + "-shm").exists()


def test_run_migrations_on_startup_no_config(tmp_path: Path) -> None:
    """Lines 88-92: run_migrations_on_startup returns early if alembic.ini missing."""
    db_path = tmp_path / "docs.db"
    with patch("wet_mcp.migrations._ALEMBIC_INI_PATH", tmp_path / "missing.ini"):
        # Should return without doing anything
        run_migrations_on_startup(db_path)
        assert not db_path.exists()


def test_run_migrations_on_startup_already_at_head(tmp_path: Path) -> None:
    """Lines 115-116: run_migrations_on_startup returns early if already at head."""
    db_path = tmp_path / "docs.db"
    # Actually initialize it to head first
    from tests.test_migrations import _make_alembic_cfg

    cfg = _make_alembic_cfg(db_path)
    command.upgrade(cfg, "head")

    # Now run the runner; it should see current == head and return
    with patch("wet_mcp.migrations.logger.debug") as mock_debug:
        run_migrations_on_startup(db_path)
        # Check if any call contains "already at head revision"
        found = False
        for call in mock_debug.call_args_list:
            if "already at head revision" in call.args[0]:
                found = True
                break
        assert found


def test_run_migrations_on_startup_head_is_baseline(tmp_path: Path) -> None:
    """Line 123: run_migrations_on_startup returns if head is baseline after stamp."""
    db_path = tmp_path / "docs.db"

    # We need to mock ScriptDirectory.get_current_head to return 'docs_001_baseline'
    with patch("alembic.script.ScriptDirectory.from_config") as mock_script_dir_class:
        mock_script = mock_script_dir_class.return_value
        mock_script.get_current_head.return_value = "docs_001_baseline"

        # Also need to mock command.stamp
        with patch("alembic.command.stamp"):
            run_migrations_on_startup(db_path)
            # If it reached line 123, it returned.
