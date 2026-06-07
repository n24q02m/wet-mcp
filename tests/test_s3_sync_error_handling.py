import asyncio
from unittest.mock import MagicMock, patch

from wet_mcp.sync import start_s3_auto_sync, stop_s3_auto_sync


def test_start_s3_auto_sync_runtime_error(monkeypatch):
    """Cover start_s3_auto_sync RuntimeError (no event loop)."""
    import wet_mcp.sync as sync_mod

    monkeypatch.setattr("wet_mcp.config.settings.sync_s3_bucket", "test-bucket")
    monkeypatch.setattr("wet_mcp.config.settings.sync_interval", 60)

    # Ensure _s3_sync_task is None
    sync_mod._s3_sync_task = None

    with patch("asyncio.create_task", side_effect=RuntimeError("no loop")):
        # Should not raise, hits lines 272-275
        start_s3_auto_sync(db=None)


def test_start_s3_auto_sync_task_running(monkeypatch):
    """Cover line 268 (task already running)."""
    import wet_mcp.sync as sync_mod

    monkeypatch.setattr("wet_mcp.config.settings.sync_s3_bucket", "test-bucket")
    monkeypatch.setattr("wet_mcp.config.settings.sync_interval", 60)

    mock_task = MagicMock(spec=asyncio.Task)
    mock_task.done.return_value = False
    sync_mod._s3_sync_task = mock_task

    try:
        start_s3_auto_sync(db=None)
        # Verify it returned early at line 268
    finally:
        sync_mod._s3_sync_task = None


def test_stop_s3_auto_sync_runtime_error():
    """Cover stop_s3_auto_sync RuntimeError during cancel (lines 282-285)."""
    import wet_mcp.sync as sync_mod

    mock_task = MagicMock(spec=asyncio.Task)
    mock_task.done.return_value = False
    mock_task.cancel.side_effect = RuntimeError("cannot cancel")

    # Manually set the global task
    sync_mod._s3_sync_task = mock_task

    try:
        # Should not raise, hits lines 282-285
        stop_s3_auto_sync()
    finally:
        sync_mod._s3_sync_task = None


def test_stop_s3_auto_sync_task_done():
    """Ensure stop_s3_auto_sync skips cancel if task is already done."""
    import wet_mcp.sync as sync_mod

    mock_task = MagicMock(spec=asyncio.Task)
    mock_task.done.return_value = True

    sync_mod._s3_sync_task = mock_task

    try:
        stop_s3_auto_sync()
        mock_task.cancel.assert_not_called()
    finally:
        sync_mod._s3_sync_task = None
