"""Tests for src/wet_mcp/sync.py — Rclone sync utilities.

Covers rclone env preparation (base64 token decoding), platform detection,
remote configuration check, and sync flow. All tests use mocks to avoid
requiring rclone or network access.
"""

import asyncio
import base64
import os
from pathlib import Path
from typing import cast
from unittest.mock import MagicMock, patch

import pytest

from wet_mcp import sync
from wet_mcp.sync import (
    _get_platform_info,
    _prepare_rclone_env,
    _run_rclone,
    check_remote_configured,
    start_auto_sync,
    stop_auto_sync,
)

# -----------------------------------------------------------------------
# _prepare_rclone_env — base64 token decoding
# -----------------------------------------------------------------------


class TestPrepareRcloneEnv:
    def test_passes_through_raw_json_token(self):
        """Raw JSON tokens are kept as-is."""
        token_json = '{"access_token": "abc123", "token_type": "Bearer"}'
        with patch.dict(os.environ, {"RCLONE_CONFIG_GDRIVE_TOKEN": token_json}):
            env = _prepare_rclone_env()
            assert env["RCLONE_CONFIG_GDRIVE_TOKEN"] == token_json

    def test_decodes_base64_token(self):
        """Base64-encoded tokens are decoded to raw JSON."""
        token_json = '{"access_token": "abc123", "token_type": "Bearer"}'
        token_b64 = base64.b64encode(token_json.encode()).decode()

        with patch.dict(os.environ, {"RCLONE_CONFIG_GDRIVE_TOKEN": token_b64}):
            env = _prepare_rclone_env()
            assert env["RCLONE_CONFIG_GDRIVE_TOKEN"] == token_json

    def test_ignores_non_token_vars(self):
        """Only *_TOKEN vars are processed for base64 decoding."""
        with patch.dict(
            os.environ,
            {
                "RCLONE_CONFIG_GDRIVE_TYPE": "drive",
                "RCLONE_CONFIG_GDRIVE_TOKEN": '{"access_token": "x"}',
            },
        ):
            env = _prepare_rclone_env()
            assert env["RCLONE_CONFIG_GDRIVE_TYPE"] == "drive"

    def test_handles_invalid_base64(self):
        """Invalid base64 is left as-is (no crash)."""
        with patch.dict(os.environ, {"RCLONE_CONFIG_TEST_TOKEN": "not-valid-b64!!!"}):
            env = _prepare_rclone_env()
            assert env["RCLONE_CONFIG_TEST_TOKEN"] == "not-valid-b64!!!"

    def test_handles_base64_non_json(self):
        """Base64 that decodes to non-JSON is left as-is."""
        not_json = base64.b64encode(b"this is not json").decode()
        with patch.dict(os.environ, {"RCLONE_CONFIG_TEST_TOKEN": not_json}):
            env = _prepare_rclone_env()
            # Should stay as original base64 since decoded content isn't valid JSON
            assert env["RCLONE_CONFIG_TEST_TOKEN"] == not_json

    def test_multiple_remotes(self):
        """Multiple remote tokens are all decoded."""
        token1 = '{"access_token": "t1"}'
        token2 = '{"access_token": "t2"}'
        b64_1 = base64.b64encode(token1.encode()).decode()
        b64_2 = base64.b64encode(token2.encode()).decode()

        with patch.dict(
            os.environ,
            {
                "RCLONE_CONFIG_GDRIVE_TOKEN": b64_1,
                "RCLONE_CONFIG_DROPBOX_TOKEN": b64_2,
            },
        ):
            env = _prepare_rclone_env()
            assert env["RCLONE_CONFIG_GDRIVE_TOKEN"] == token1
            assert env["RCLONE_CONFIG_DROPBOX_TOKEN"] == token2


# -----------------------------------------------------------------------
# _get_platform_info
# -----------------------------------------------------------------------


class TestGetPlatformInfo:
    def test_returns_three_values(self):
        """Returns (os_name, arch, ext) tuple."""
        os_name, arch, ext = _get_platform_info()
        assert os_name in ("windows", "osx", "linux")
        assert arch in ("amd64", "arm64", "386")
        assert ext in ("", ".exe")

    def test_windows_has_exe(self):
        """Windows platform returns .exe extension."""
        with (
            patch("wet_mcp.sync.platform.system", return_value="Windows"),
            patch("wet_mcp.sync.platform.machine", return_value="AMD64"),
        ):
            os_name, arch, ext = _get_platform_info()
            assert os_name == "windows"
            assert ext == ".exe"

    def test_linux_no_exe(self):
        """Linux platform returns no extension."""
        with (
            patch("wet_mcp.sync.platform.system", return_value="Linux"),
            patch("wet_mcp.sync.platform.machine", return_value="x86_64"),
        ):
            os_name, arch, ext = _get_platform_info()
            assert os_name == "linux"
            assert arch == "amd64"
            assert ext == ""

    def test_macos_arm64(self):
        """macOS ARM is detected correctly."""
        with (
            patch("wet_mcp.sync.platform.system", return_value="Darwin"),
            patch("wet_mcp.sync.platform.machine", return_value="arm64"),
        ):
            os_name, arch, ext = _get_platform_info()
            assert os_name == "osx"
            assert arch == "arm64"


# -----------------------------------------------------------------------
# check_remote_configured
# -----------------------------------------------------------------------


class TestCheckRemoteConfigured:
    @pytest.mark.asyncio
    async def test_remote_found(self):
        """Returns True when remote is in rclone listremotes output."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "gdrive:\ndropbox:\n"

        with patch("wet_mcp.sync._run_rclone", return_value=mock_result):
            assert (
                await check_remote_configured(Path("/usr/bin/rclone"), "gdrive") is True
            )
            assert (
                await check_remote_configured(Path("/usr/bin/rclone"), "dropbox")
                is True
            )

    @pytest.mark.asyncio
    async def test_remote_not_found(self):
        """Returns False when remote is not in listremotes output."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "gdrive:\n"

        with patch("wet_mcp.sync._run_rclone", return_value=mock_result):
            assert (
                await check_remote_configured(Path("/usr/bin/rclone"), "s3bucket")
                is False
            )

    @pytest.mark.asyncio
    async def test_rclone_error(self):
        """Returns False when rclone command fails."""
        mock_result = MagicMock()
        mock_result.returncode = 1

        with patch("wet_mcp.sync._run_rclone", return_value=mock_result):
            assert (
                await check_remote_configured(Path("/usr/bin/rclone"), "gdrive")
                is False
            )

    @pytest.mark.asyncio
    async def test_empty_output(self):
        """Returns False when no remotes are configured."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = ""

        with patch("wet_mcp.sync._run_rclone", return_value=mock_result):
            assert (
                await check_remote_configured(Path("/usr/bin/rclone"), "gdrive")
                is False
            )


# -----------------------------------------------------------------------
# _run_rclone
# -----------------------------------------------------------------------


class TestRunRclone:
    def test_run_rclone_constructs_command(self):
        """_run_rclone calls subprocess.run with correct args."""
        mock_result = MagicMock()
        mock_result.returncode = 0

        rclone_path = Path("/usr/bin/rclone")

        with (
            patch("wet_mcp.sync.subprocess.run", return_value=mock_result) as mock_run,
            patch("wet_mcp.sync._prepare_rclone_env", return_value=os.environ.copy()),
        ):
            _run_rclone(rclone_path, ["listremotes"], timeout=10)

            mock_run.assert_called_once()
            call_args = mock_run.call_args
            assert call_args[0][0] == [str(rclone_path), "listremotes"]
            assert call_args[1]["timeout"] == 10
            assert call_args[1]["capture_output"] is True
            assert call_args[1]["text"] is True


@pytest.fixture(autouse=True)
def clean_sync_task():
    """Fixture to reset global _sync_task state before and after each test."""
    initial = sync._sync_task
    sync._sync_task = None
    yield
    if sync._sync_task and not sync._sync_task.done():
        sync._sync_task.cancel()
    sync._sync_task = initial


class TestAutoSyncLifecycle:
    @pytest.mark.asyncio
    async def test_stop_auto_sync_no_task(self):
        sync._sync_task = None
        stop_auto_sync()
        assert sync._sync_task is None

    @pytest.mark.asyncio
    async def test_stop_auto_sync_already_done(self):
        future = asyncio.Future()
        future.set_result(None)
        sync._sync_task = cast(asyncio.Task, future)
        stop_auto_sync()
        assert sync._sync_task is future
        assert not future.cancelled()

    @pytest.mark.asyncio
    async def test_stop_auto_sync_running(self):
        future = asyncio.Future()
        sync._sync_task = cast(asyncio.Task, future)
        stop_auto_sync()
        assert sync._sync_task is None
        assert future.cancelled()

    @pytest.mark.asyncio
    async def test_start_auto_sync_disabled(self, clean_sync_task):
        db_mock = MagicMock()
        with patch("wet_mcp.sync.settings.sync_enabled", False):
            start_auto_sync(db_mock)
            assert sync._sync_task is None

    @pytest.mark.asyncio
    async def test_start_auto_sync_interval_zero(self, clean_sync_task):
        db_mock = MagicMock()
        with (
            patch("wet_mcp.sync.settings.sync_enabled", True),
            patch("wet_mcp.sync.settings.sync_interval", 0),
        ):
            start_auto_sync(db_mock)
            assert sync._sync_task is None

    @pytest.mark.asyncio
    async def test_start_auto_sync_already_running(self, clean_sync_task):
        db_mock = MagicMock()
        future = asyncio.Future()
        sync._sync_task = cast(asyncio.Task, future)

        with (
            patch("wet_mcp.sync.settings.sync_enabled", True),
            patch("wet_mcp.sync.settings.sync_interval", 10),
        ):
            start_auto_sync(db_mock)
            assert sync._sync_task is future

    @pytest.mark.asyncio
    @patch("wet_mcp.sync._auto_sync_loop")
    async def test_start_auto_sync_creates_task(self, mock_loop, clean_sync_task):
        db_mock = MagicMock()

        async def dummy_loop(*args):
            pass

        mock_loop.side_effect = dummy_loop

        with (
            patch("wet_mcp.sync.settings.sync_enabled", True),
            patch("wet_mcp.sync.settings.sync_interval", 10),
        ):
            start_auto_sync(db_mock)
            assert sync._sync_task is not None
            assert not sync._sync_task.done()

            await sync._sync_task


# -----------------------------------------------------------------------
# sync.sync_pull
# -----------------------------------------------------------------------


class TestSyncPull:
    @pytest.mark.asyncio
    async def test_sync_pull_success(self):
        """Returns downloaded file path on success."""
        rclone_path = Path("/mock/rclone")
        db_path = Path("/mock/db/local.sqlite")
        remote = "gdrive"
        folder = "backup"

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stderr = ""

        with (
            patch(
                "wet_mcp.sync.asyncio.to_thread", return_value=mock_result
            ) as mock_thread,
            patch("pathlib.Path.mkdir"),
            patch("pathlib.Path.exists", return_value=True),
        ):
            result = await sync.sync_pull(rclone_path, db_path, remote, folder)

            assert result is not None
            assert result.name == "remote_local.sqlite"
            assert str(result.parent).endswith("sync_temp")

            mock_thread.assert_called_once()
            args = mock_thread.call_args[0]
            assert args[1] == rclone_path
            assert "copyto" in args[2]

    @pytest.mark.asyncio
    async def test_sync_pull_failure_return_code(self):
        """Returns None and cleans up when command fails."""
        rclone_path = Path("/mock/rclone")
        db_path = Path("/mock/db/local.sqlite")
        remote = "gdrive"
        folder = "backup"

        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stderr = "Command failed"

        with (
            patch("wet_mcp.sync.asyncio.to_thread", return_value=mock_result),
            patch("pathlib.Path.mkdir"),
            patch("pathlib.Path.unlink") as mock_unlink,
        ):
            result = await sync.sync_pull(rclone_path, db_path, remote, folder)

            assert result is None
            mock_unlink.assert_called_once_with(missing_ok=True)

    @pytest.mark.asyncio
    async def test_sync_pull_failure_file_missing(self):
        """Returns None and cleans up when downloaded file is missing despite success exit code."""
        rclone_path = Path("/mock/rclone")
        db_path = Path("/mock/db/local.sqlite")
        remote = "gdrive"
        folder = "backup"

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stderr = ""

        with (
            patch("wet_mcp.sync.asyncio.to_thread", return_value=mock_result),
            patch("pathlib.Path.mkdir"),
            patch("pathlib.Path.exists", return_value=False),
            patch("pathlib.Path.unlink") as mock_unlink,
        ):
            result = await sync.sync_pull(rclone_path, db_path, remote, folder)

            assert result is None
            mock_unlink.assert_called_once_with(missing_ok=True)


# -----------------------------------------------------------------------
# _validate_rclone_args
# -----------------------------------------------------------------------


class TestValidateRcloneArgs:
    def test_validate_rclone_args_allowed(self):
        """_validate_rclone_args allows safe commands and flags."""
        from wet_mcp.sync import _validate_rclone_args

        with patch("wet_mcp.config.settings") as mock_settings:
            mock_settings.sync_remote = "gdrive"
            mock_settings.sync_provider = "drive"
            mock_settings.sync_folder = "docs"
            _validate_rclone_args(
                ["copy", "--progress", "--", "gdrive:docs", "/tmp/local"]
            )
            _validate_rclone_args(["listremotes"])

    def test_validate_rclone_args_disallowed_cmd(self):
        """_validate_rclone_args blocks unsafe commands."""
        from wet_mcp.sync import _validate_rclone_args

        with patch("wet_mcp.config.settings") as mock_settings:
            mock_settings.sync_remote = "gdrive"
            mock_settings.sync_provider = "drive"
            mock_settings.sync_folder = "docs"
            with pytest.raises(ValueError, match="Disallowed rclone command: delete"):
                _validate_rclone_args(["delete", "gdrive:docs"])

    def test_validate_rclone_args_disallowed_flag(self):
        """_validate_rclone_args blocks unsafe flags."""
        from wet_mcp.sync import _validate_rclone_args

        with patch("wet_mcp.config.settings") as mock_settings:
            mock_settings.sync_remote = "gdrive"
            mock_settings.sync_provider = "drive"
            mock_settings.sync_folder = "docs"
            with pytest.raises(ValueError, match="Disallowed rclone flag: --config"):
                _validate_rclone_args(
                    ["copy", "--config", "/etc/passwd", "gdrive:docs", "/tmp/local"]
                )
