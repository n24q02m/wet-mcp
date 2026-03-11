"""Tests to improve wet_mcp.sync coverage for new token management code."""

import json
import os
import subprocess
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from wet_mcp.sync import (
    _extract_zip_sync,
    _has_token_available,
    _interactive_auth,
    _prepare_rclone_env,
    setup_sync,
    sync_full,
)


class TestHasTokenAvailable:
    """Cover _has_token_available function."""

    @patch("wet_mcp.sync.settings")
    def test_env_var_present(self, mock_settings):
        mock_settings.sync_remote = "gdrive"
        mock_settings.sync_provider = "drive"
        with patch.dict(
            os.environ, {"RCLONE_CONFIG_GDRIVE_TOKEN": '{"access_token":"x"}'}
        ):
            assert _has_token_available() is True

    @patch("wet_mcp.sync.settings")
    @patch("wet_mcp.token_store.load_token", return_value={"access_token": "y"})
    def test_local_token(self, _mock_load, mock_settings):
        mock_settings.sync_remote = "gdrive"
        mock_settings.sync_provider = "drive"
        with patch.dict(os.environ, {}, clear=True):
            assert _has_token_available() is True

    @patch("wet_mcp.sync.settings")
    @patch("wet_mcp.token_store.load_token", return_value=None)
    def test_no_token(self, _mock_load, mock_settings):
        mock_settings.sync_remote = "gdrive"
        mock_settings.sync_provider = "drive"
        with patch.dict(os.environ, {}, clear=True):
            assert _has_token_available() is False


class TestInteractiveAuth:
    """Cover _interactive_auth function."""

    @pytest.mark.asyncio
    @patch("wet_mcp.token_store.save_token")
    async def test_success(self, mock_save):
        token_json = '{"access_token":"tok123"}'
        result = subprocess.CompletedProcess(
            args=[], returncode=0, stdout=f"----\n{token_json}\n----"
        )
        with patch("wet_mcp.sync.asyncio.to_thread", return_value=result):
            token = await _interactive_auth(Path("/rclone"), "drive")

        assert token == {"access_token": "tok123"}
        mock_save.assert_called_once_with("drive", {"access_token": "tok123"})

    @pytest.mark.asyncio
    async def test_auth_failure(self):
        result = subprocess.CompletedProcess(args=[], returncode=1, stdout="")
        with patch("wet_mcp.sync.asyncio.to_thread", return_value=result):
            token = await _interactive_auth(Path("/rclone"), "drive")
        assert token is None

    @pytest.mark.asyncio
    async def test_no_token_in_output(self):
        result = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="no token here"
        )
        with patch("wet_mcp.sync.asyncio.to_thread", return_value=result):
            token = await _interactive_auth(Path("/rclone"), "drive")
        assert token is None

    @pytest.mark.asyncio
    async def test_invalid_json_token(self):
        result = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout='----\n{"access_token": invalid}\n----',
        )
        with (
            patch("wet_mcp.sync.asyncio.to_thread", return_value=result),
            patch(
                "wet_mcp.sync._extract_token", return_value='{"access_token": invalid}'
            ),
        ):
            token = await _interactive_auth(Path("/rclone"), "drive")
        assert token is None


class TestPrepareRcloneEnvLocalToken:
    """Cover _prepare_rclone_env local token loading."""

    @patch("wet_mcp.sync.settings")
    @patch("wet_mcp.token_store.load_token")
    def test_local_token_loaded(self, mock_load, mock_settings):
        mock_settings.sync_remote = "gdrive"
        mock_settings.sync_provider = "drive"
        mock_load.return_value = {"access_token": "local_tok"}

        with patch.dict(os.environ, {}, clear=True):
            env = _prepare_rclone_env()

        assert env["RCLONE_CONFIG_GDRIVE_TOKEN"] == json.dumps(
            {"access_token": "local_tok"}
        )
        assert env["RCLONE_CONFIG_GDRIVE_TYPE"] == "drive"


class TestSyncFullInteractiveAuth:
    """Cover sync_full auto-provision token path."""

    @pytest.mark.asyncio
    @patch("wet_mcp.sync.settings")
    @patch("wet_mcp.sync.ensure_rclone")
    @patch("wet_mcp.sync._has_token_available", return_value=False)
    @patch("wet_mcp.sync._interactive_auth", return_value=None)
    async def test_no_token_auth_fails(
        self, _mock_auth, _mock_has, mock_ensure, mock_settings
    ):
        mock_settings.sync_enabled = True
        mock_settings.sync_remote = "gdrive"
        mock_settings.sync_provider = "drive"
        mock_ensure.return_value = Path("/rclone")

        result = await sync_full(MagicMock())
        assert result["status"] == "error"
        assert "No sync token available" in result["message"]

    @pytest.mark.asyncio
    @patch("wet_mcp.sync.settings")
    @patch("wet_mcp.sync.ensure_rclone")
    @patch("wet_mcp.sync._has_token_available", return_value=False)
    @patch("wet_mcp.sync._interactive_auth", return_value={"access_token": "ok"})
    @patch("wet_mcp.sync.check_remote_configured", return_value=False)
    async def test_auth_succeeds_but_remote_not_configured(
        self, _mock_check, _mock_auth, _mock_has, mock_ensure, mock_settings
    ):
        mock_settings.sync_enabled = True
        mock_settings.sync_remote = "gdrive"
        mock_settings.sync_provider = "drive"
        mock_ensure.return_value = Path("/rclone")

        result = await sync_full(MagicMock())
        assert result["status"] == "error"
        assert "not configured" in result["message"]


class TestExtractZipSync:
    """Cover _extract_zip_sync function."""

    def test_extracts_binary(self, tmp_path):
        import zipfile

        # Create a test zip with a rclone binary
        zip_path = tmp_path / "test.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("rclone-v1/rclone", b"binary_data")

        target = tmp_path / "rclone"
        result = _extract_zip_sync(zip_path, target, "rclone")
        assert result is True
        assert target.exists()

    def test_binary_not_found(self, tmp_path):
        import zipfile

        zip_path = tmp_path / "test.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("other_file.txt", "not a binary")

        target = tmp_path / "rclone"
        result = _extract_zip_sync(zip_path, target, "rclone")
        assert result is False


class TestSetupSyncTokenSuccess:
    """Cover setup_sync with successful token save (non-drive remote)."""

    @patch("wet_mcp.sync._get_rclone_path")
    @patch("wet_mcp.sync.subprocess.run")
    @patch("wet_mcp.sync._extract_token")
    def test_non_drive_success(self, mock_extract, mock_run, mock_get_path, capsys):
        mock_get_path.return_value = Path("/rclone")
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="output"
        )
        mock_extract.return_value = '{"access_token":"tok"}'

        with (
            patch("wet_mcp.sync.json.loads", return_value={"access_token": "tok"}),
            patch("wet_mcp.token_store.save_token"),
            patch(
                "wet_mcp.token_store.get_token_path",
                return_value=Path("/home/.wet-mcp/tokens/s3.json"),
            ),
        ):
            setup_sync("s3")

        captured = capsys.readouterr()
        assert "SUCCESS! Token saved" in captured.out
        assert "SYNC_PROVIDER" in captured.out
        assert "SYNC_REMOTE" in captured.out

    @patch("wet_mcp.sync._get_rclone_path")
    @patch("wet_mcp.sync.subprocess.run")
    @patch("wet_mcp.sync._extract_token")
    def test_token_json_decode_error(
        self, mock_extract, mock_run, mock_get_path, capsys
    ):
        """Cover the JSONDecodeError fallback in setup_sync."""
        mock_get_path.return_value = Path("/rclone")
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="output"
        )
        mock_extract.return_value = '{"access_token":"tok"}'

        with patch(
            "wet_mcp.sync.json.loads", side_effect=json.JSONDecodeError("err", "doc", 0)
        ):
            setup_sync("drive")

        captured = capsys.readouterr()
        assert "Base64 token" in captured.out


class TestDownloadRcloneChecksum:
    """Cover _download_rclone checksum verification paths."""

    @pytest.mark.asyncio
    @patch("wet_mcp.sync._get_rclone_dir")
    @patch("wet_mcp.sync._get_platform_info")
    @patch.object(Path, "exists")
    @patch("wet_mcp.sync.httpx.AsyncClient")
    @patch("wet_mcp.sync._extract_zip_sync")
    @patch.object(Path, "mkdir")
    @patch.object(Path, "chmod")
    @patch.object(Path, "stat")
    @patch.object(Path, "unlink")
    async def test_checksum_mismatch(
        self,
        mock_unlink,
        mock_stat,
        mock_chmod,
        mock_mkdir,
        mock_extract_zip,
        mock_client,
        mock_exists,
        mock_info,
        mock_dir,
    ):
        from wet_mcp.sync import _download_rclone

        mock_info.return_value = ("linux", "amd64", "")
        mock_dir.return_value = Path("/mock/dir")
        mock_exists.side_effect = [False]

        mock_resp = MagicMock()
        mock_resp.content = b"zip_content"
        mock_resp.raise_for_status = MagicMock()

        mock_client_instance = AsyncMock()
        mock_client_instance.get = AsyncMock(return_value=mock_resp)
        mock_client.return_value.__aenter__ = AsyncMock(
            return_value=mock_client_instance
        )
        mock_client.return_value.__aexit__ = AsyncMock(return_value=None)

        # Set checksum that won't match
        with patch.dict(
            "wet_mcp.sync._RCLONE_CHECKSUMS",
            {
                "linux-amd64": "0000000000000000000000000000000000000000000000000000000000000000"
            },
        ):
            res = await _download_rclone()

        assert res is None
