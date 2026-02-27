import asyncio
import base64
import subprocess
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import wet_mcp.sync
from wet_mcp.sync import (
    _auto_sync_loop,
    _download_rclone,
    _extract_token,
    _get_platform_info,
    _get_rclone_dir,
    _get_rclone_path,
    _prepare_rclone_env,
    _run_rclone,
    check_remote_configured,
    ensure_rclone,
    setup_sync,
    start_auto_sync,
    stop_auto_sync,
    sync_full,
    sync_pull,
    sync_push,
)


@pytest.fixture
def mock_settings():
    with patch("wet_mcp.sync.settings") as mock_settings:
        mock_settings.get_data_dir.return_value = Path("/mock/data/dir")
        mock_settings.get_db_path.return_value = Path("/mock/data/dir/db.sqlite")
        mock_settings.sync_enabled = True
        mock_settings.sync_remote = "gdrive"
        mock_settings.sync_folder = "wet_sync"
        mock_settings.sync_interval = 60
        yield mock_settings


def test_get_rclone_dir(mock_settings):
    assert _get_rclone_dir() == Path("/mock/data/dir/bin")


@patch("wet_mcp.sync.shutil.which")
@patch("wet_mcp.sync.sys")
@patch.object(Path, "exists")
def test_get_rclone_path_system(mock_exists, mock_sys, mock_which):
    mock_which.return_value = "/usr/bin/rclone"
    assert _get_rclone_path() == Path("/usr/bin/rclone")
    mock_which.assert_called_once_with("rclone")


@patch("wet_mcp.sync.shutil.which")
@patch("wet_mcp.sync.sys")
@patch.object(Path, "exists")
@patch("wet_mcp.sync._get_rclone_dir")
def test_get_rclone_path_bundled_win(mock_get_dir, mock_exists, mock_sys, mock_which):
    mock_which.return_value = None
    mock_sys.platform = "win32"
    mock_get_dir.return_value = Path("/mock/dir")
    mock_exists.return_value = True
    assert _get_rclone_path() == Path("/mock/dir/rclone.exe")


@patch("wet_mcp.sync.shutil.which")
@patch("wet_mcp.sync.sys")
@patch.object(Path, "exists")
@patch("wet_mcp.sync._get_rclone_dir")
def test_get_rclone_path_bundled_unix(mock_get_dir, mock_exists, mock_sys, mock_which):
    mock_which.return_value = None
    mock_sys.platform = "linux"
    mock_get_dir.return_value = Path("/mock/dir")
    mock_exists.return_value = True
    assert _get_rclone_path() == Path("/mock/dir/rclone")


@patch("wet_mcp.sync.shutil.which")
@patch("wet_mcp.sync.sys")
@patch.object(Path, "exists")
def test_get_rclone_path_none(mock_exists, mock_sys, mock_which):
    mock_which.return_value = None
    mock_exists.return_value = False
    assert _get_rclone_path() is None


@pytest.mark.parametrize(
    "system, machine, exp_os, exp_arch, exp_ext",
    [
        ("Windows", "AMD64", "windows", "amd64", ".exe"),
        ("Windows", "i386", "windows", "386", ".exe"),
        ("Darwin", "arm64", "osx", "arm64", ""),
        ("Darwin", "x86_64", "osx", "amd64", ""),
        ("Linux", "aarch64", "linux", "arm64", ""),
        ("Linux", "x86_64", "linux", "amd64", ""),
        ("Linux", "unknown", "linux", "amd64", ""),
    ],
)
@patch("wet_mcp.sync.platform.system")
@patch("wet_mcp.sync.platform.machine")
def test_get_platform_info(
    mock_machine, mock_system, system, machine, exp_os, exp_arch, exp_ext
):
    mock_system.return_value = system
    mock_machine.return_value = machine
    assert _get_platform_info() == (exp_os, exp_arch, exp_ext)


@pytest.mark.asyncio
@patch("wet_mcp.sync._get_rclone_dir")
@patch("wet_mcp.sync._get_platform_info")
@patch.object(Path, "exists")
@patch.object(Path, "mkdir")
async def test_download_rclone_already_exists(
    mock_mkdir, mock_exists, mock_info, mock_dir
):
    mock_info.return_value = ("linux", "amd64", "")
    mock_dir.return_value = Path("/mock/dir")
    mock_exists.return_value = True
    res = await _download_rclone()
    assert res == Path("/mock/dir/rclone")


@pytest.mark.asyncio
@patch("wet_mcp.sync._get_rclone_dir")
@patch("wet_mcp.sync._get_platform_info")
@patch.object(Path, "exists")
@patch("wet_mcp.sync.httpx.AsyncClient")
@patch("wet_mcp.sync.tempfile.NamedTemporaryFile")
@patch("wet_mcp.sync.zipfile.ZipFile")
@patch.object(Path, "mkdir")
@patch.object(Path, "write_bytes")
@patch.object(Path, "chmod")
@patch.object(Path, "stat")
@patch.object(Path, "unlink")
async def test_download_rclone_success(
    mock_unlink,
    mock_stat,
    mock_chmod,
    mock_write,
    mock_mkdir,
    mock_zip,
    mock_temp,
    mock_client,
    mock_exists,
    mock_info,
    mock_dir,
):
    mock_info.return_value = ("linux", "amd64", "")
    mock_dir.return_value = Path("/mock/dir")

    # Path.exists is called twice potentially, first time false
    mock_exists.side_effect = [False]

    # Mock httpx response
    mock_resp = MagicMock()
    mock_resp.content = b"zip_content"

    # Setup AsyncClient context manager
    mock_client_instance = AsyncMock()
    mock_client_instance.get = AsyncMock(return_value=mock_resp)
    mock_client.return_value.__aenter__ = AsyncMock(return_value=mock_client_instance)
    mock_client.return_value.__aexit__ = AsyncMock(return_value=None)

    # Setup tempfile
    mock_tmp = MagicMock()
    mock_tmp.name = "/tmp/fake.zip"
    mock_temp.return_value.__enter__.return_value = mock_tmp

    # Setup zipfile
    mock_zf = MagicMock()
    mock_info1 = MagicMock()
    mock_info1.filename = "rclone-v1.68.2-linux-amd64/rclone"
    mock_info1.is_dir.return_value = False
    mock_zf.infolist.return_value = [mock_info1]

    mock_src = MagicMock()
    mock_src.read.return_value = b"binary_content"
    mock_zf.open.return_value.__enter__.return_value = mock_src

    mock_zip.return_value.__enter__.return_value = mock_zf

    # Setup stat for chmod
    mock_stat_result = MagicMock()
    mock_stat_result.st_mode = 0o644
    mock_stat.return_value = mock_stat_result

    res = await _download_rclone()

    assert res == Path("/mock/dir/rclone")
    mock_client_instance.get.assert_called_once()
    mock_write.assert_called_once_with(b"binary_content")
    mock_chmod.assert_called_once()
    mock_unlink.assert_called_once_with(missing_ok=True)


@pytest.mark.asyncio
@patch("wet_mcp.sync._get_rclone_dir")
@patch("wet_mcp.sync._get_platform_info")
@patch.object(Path, "exists")
@patch("wet_mcp.sync.httpx.AsyncClient")
@patch.object(Path, "mkdir")
async def test_download_rclone_http_error(
    mock_mkdir, mock_client, mock_exists, mock_info, mock_dir
):
    mock_info.return_value = ("linux", "amd64", "")
    mock_dir.return_value = Path("/mock/dir")
    mock_exists.return_value = False

    mock_client_instance = AsyncMock()
    mock_client_instance.get = AsyncMock(side_effect=Exception("Network error"))
    mock_client.return_value.__aenter__ = AsyncMock(return_value=mock_client_instance)
    mock_client.return_value.__aexit__ = AsyncMock(return_value=None)

    res = await _download_rclone()
    assert res is None


@pytest.mark.asyncio
@patch("wet_mcp.sync._get_rclone_path")
@patch("wet_mcp.sync._download_rclone")
async def test_ensure_rclone_exists(mock_download, mock_get_path):
    mock_get_path.return_value = Path("/bin/rclone")
    res = await ensure_rclone()
    assert res == Path("/bin/rclone")
    mock_download.assert_not_called()


@pytest.mark.asyncio
@patch("wet_mcp.sync._get_rclone_path")
@patch("wet_mcp.sync._download_rclone")
async def test_ensure_rclone_download(mock_download, mock_get_path):
    mock_get_path.return_value = None
    mock_download.return_value = Path("/downloaded/rclone")
    res = await ensure_rclone()
    assert res == Path("/downloaded/rclone")
    mock_download.assert_called_once()


@patch(
    "wet_mcp.sync.os.environ",
    {
        "NORMAL_VAR": "val",
        "RCLONE_CONFIG_GDRIVE_TOKEN": base64.b64encode(
            b'{"access_token":"abc"}'
        ).decode(),
    },
)
def test_prepare_rclone_env_base64():
    env = _prepare_rclone_env()
    assert env["NORMAL_VAR"] == "val"
    assert env["RCLONE_CONFIG_GDRIVE_TOKEN"] == '{"access_token":"abc"}'


@patch(
    "wet_mcp.sync.os.environ", {"RCLONE_CONFIG_GDRIVE_TOKEN": '{"access_token":"raw"}'}
)
def test_prepare_rclone_env_raw_json():
    env = _prepare_rclone_env()
    assert env["RCLONE_CONFIG_GDRIVE_TOKEN"] == '{"access_token":"raw"}'


@patch("wet_mcp.sync.os.environ", {"RCLONE_CONFIG_GDRIVE_TOKEN": "invalid_base64!"})
def test_prepare_rclone_env_invalid_base64():
    env = _prepare_rclone_env()
    assert env["RCLONE_CONFIG_GDRIVE_TOKEN"] == "invalid_base64!"


@patch("wet_mcp.sync.subprocess.run")
@patch("wet_mcp.sync._prepare_rclone_env")
def test_run_rclone(mock_env, mock_run):
    mock_env.return_value = {"ENV_VAR": "1"}
    mock_run.return_value = subprocess.CompletedProcess(
        args=[], returncode=0, stdout="out"
    )

    res = _run_rclone(Path("/bin/rclone"), ["arg1"], 10)

    assert res.returncode == 0
    mock_run.assert_called_once_with(
        ["/bin/rclone", "arg1"],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=10,
        env={"ENV_VAR": "1"},
    )


@pytest.mark.asyncio
@patch("wet_mcp.sync._run_rclone")
async def test_check_remote_configured_success(mock_run):
    mock_run.return_value = subprocess.CompletedProcess(
        args=[], returncode=0, stdout="gdrive:\nother:"
    )
    res = await check_remote_configured(Path("/rclone"), "gdrive")
    assert res is True

    res2 = await check_remote_configured(Path("/rclone"), "missing")
    assert res2 is False


@pytest.mark.asyncio
@patch("wet_mcp.sync._run_rclone")
async def test_check_remote_configured_fail(mock_run):
    mock_run.return_value = subprocess.CompletedProcess(
        args=[], returncode=1, stdout=""
    )
    res = await check_remote_configured(Path("/rclone"), "gdrive")
    assert res is False


@pytest.mark.asyncio
@patch("wet_mcp.sync._run_rclone")
async def test_sync_push(mock_run):
    mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0)
    res = await sync_push(Path("/rclone"), Path("/db/db.sqlite"), "gdrive", "folder")
    assert res is True
    mock_run.assert_called_once()
    assert mock_run.call_args[0][1] == [
        "copy",
        "/db/db.sqlite",
        "gdrive:folder",
        "--progress",
    ]


@pytest.mark.asyncio
@patch("wet_mcp.sync._run_rclone")
async def test_sync_push_fail(mock_run):
    mock_run.return_value = subprocess.CompletedProcess(
        args=[], returncode=1, stderr="error"
    )
    res = await sync_push(Path("/rclone"), Path("/db/db.sqlite"), "gdrive", "folder")
    assert res is False


@pytest.mark.asyncio
@patch("wet_mcp.sync._run_rclone")
@patch.object(Path, "mkdir")
@patch.object(Path, "exists")
async def test_sync_pull(mock_exists, mock_mkdir, mock_run):
    mock_exists.return_value = True
    mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0)

    res = await sync_pull(Path("/rclone"), Path("/db/db.sqlite"), "gdrive", "folder")

    assert res == Path("/db/sync_temp/remote_db.sqlite")
    mock_run.assert_called_once()
    assert mock_run.call_args[0][1] == [
        "copyto",
        "gdrive:folder/db.sqlite",
        "/db/sync_temp/remote_db.sqlite",
        "--progress",
    ]


@pytest.mark.asyncio
@patch("wet_mcp.sync._run_rclone")
@patch.object(Path, "mkdir")
@patch.object(Path, "exists")
@patch.object(Path, "unlink")
async def test_sync_pull_fail(mock_unlink, mock_exists, mock_mkdir, mock_run):
    mock_exists.return_value = False
    mock_run.return_value = subprocess.CompletedProcess(
        args=[], returncode=1, stderr="error"
    )

    res = await sync_pull(Path("/rclone"), Path("/db/db.sqlite"), "gdrive", "folder")
    assert res is None
    mock_unlink.assert_called_once()


@pytest.mark.asyncio
@patch("wet_mcp.sync.settings")
async def test_sync_full_disabled(mock_settings):
    mock_settings.sync_enabled = False
    res = await sync_full(MagicMock())
    assert res["status"] == "disabled"


@pytest.mark.asyncio
@patch("wet_mcp.sync.settings")
@patch("wet_mcp.sync.ensure_rclone")
async def test_sync_full_no_rclone(mock_ensure, mock_settings):
    mock_settings.sync_enabled = True
    mock_settings.sync_remote = "gdrive"
    mock_ensure.return_value = None
    res = await sync_full(MagicMock())
    assert res["status"] == "error"
    assert "rclone not available" in res["message"]


@pytest.mark.asyncio
@patch("wet_mcp.sync.settings")
@patch("wet_mcp.sync.ensure_rclone")
@patch("wet_mcp.sync.check_remote_configured")
async def test_sync_full_not_configured(mock_check, mock_ensure, mock_settings):
    mock_settings.sync_enabled = True
    mock_settings.sync_remote = "gdrive"
    mock_ensure.return_value = Path("/rclone")
    mock_check.return_value = False

    res = await sync_full(MagicMock())
    assert res["status"] == "error"
    assert "not configured" in res["message"]


@pytest.mark.asyncio
@patch("wet_mcp.sync.settings")
@patch("wet_mcp.sync.ensure_rclone")
@patch("wet_mcp.sync.check_remote_configured")
@patch("wet_mcp.sync.sync_pull")
@patch("wet_mcp.sync.sync_push")
@patch("wet_mcp.db.DocsDB")
async def test_sync_full_success(
    mock_DocsDB, mock_push, mock_pull, mock_check, mock_ensure, mock_settings
):
    mock_settings.sync_enabled = True
    mock_settings.sync_remote = "gdrive"
    mock_settings.sync_folder = "folder"
    mock_settings.get_db_path.return_value = Path("/db/db.sqlite")

    mock_ensure.return_value = Path("/rclone")
    mock_check.return_value = True

    # Setup pull
    mock_pull.return_value = Path("/tmp/remote.sqlite")
    mock_push.return_value = True

    # Setup remote db
    mock_remote_db = MagicMock()
    mock_remote_db.export_jsonl.return_value = '{"id":"test"}'
    mock_DocsDB.return_value = mock_remote_db

    # Setup local db
    mock_local_db = MagicMock()
    mock_local_db.import_jsonl.return_value = {"libraries": 1}

    res = await sync_full(mock_local_db)

    assert res["status"] == "ok"
    assert res["pull"] == {"libraries": 1}
    assert res["push"] == {"success": True}


@pytest.mark.asyncio
@patch("wet_mcp.sync.settings")
@patch("wet_mcp.sync.ensure_rclone")
@patch("wet_mcp.sync.check_remote_configured")
@patch("wet_mcp.sync.sync_pull")
@patch("wet_mcp.sync.sync_push")
async def test_sync_full_no_remote_file(
    mock_push, mock_pull, mock_check, mock_ensure, mock_settings
):
    mock_settings.sync_enabled = True
    mock_settings.sync_remote = "gdrive"
    mock_ensure.return_value = Path("/rclone")
    mock_check.return_value = True
    mock_pull.return_value = None
    mock_push.return_value = True

    res = await sync_full(MagicMock())
    assert res["status"] == "ok"
    assert res["pull"]["note"] == "No remote DB found"
    assert res["push"]["success"] is True


@pytest.mark.asyncio
@patch("wet_mcp.sync.settings")
@patch("wet_mcp.sync.ensure_rclone")
@patch("wet_mcp.sync.check_remote_configured")
@patch("wet_mcp.sync.sync_pull")
@patch("wet_mcp.sync.sync_push")
@patch("wet_mcp.db.DocsDB")
async def test_sync_full_merge_exception(
    mock_DocsDB, mock_push, mock_pull, mock_check, mock_ensure, mock_settings
):
    mock_settings.sync_enabled = True
    mock_settings.sync_remote = "gdrive"
    mock_ensure.return_value = Path("/rclone")
    mock_check.return_value = True
    mock_pull.return_value = Path("/tmp/remote.sqlite")
    mock_push.return_value = True

    mock_DocsDB.side_effect = Exception("DB Error")

    res = await sync_full(MagicMock())
    assert res["status"] == "ok"
    assert "error" in res["pull"]
    assert res["pull"]["error"] == "DB Error"


def test_extract_token():
    out1 = 'some text\n----\n{"access_token":"123"}\n----\nmore text'
    assert _extract_token(out1) == '{"access_token":"123"}'

    out2 = 'Paste this:\n{"access_token":"456", "other":1}\nEnd'
    assert _extract_token(out2) == '{"access_token":"456", "other":1}'

    out3 = "No token here"
    assert _extract_token(out3) is None


@patch("wet_mcp.sync.settings")
@patch("wet_mcp.sync.asyncio.sleep")
@patch("wet_mcp.sync.sync_full")
@pytest.mark.asyncio
async def test_auto_sync_loop_stops_on_cancel(mock_sync, mock_sleep, mock_settings):
    mock_settings.sync_interval = 60
    mock_sleep.side_effect = asyncio.CancelledError()

    await _auto_sync_loop(MagicMock())
    mock_sync.assert_not_called()


@patch("wet_mcp.sync.settings")
@pytest.mark.asyncio
async def test_auto_sync_loop_disabled(mock_settings):
    mock_settings.sync_interval = 0
    await _auto_sync_loop(MagicMock())


@patch("wet_mcp.sync.settings")
@patch("wet_mcp.sync.asyncio.create_task")
def test_start_auto_sync(mock_create, mock_settings):
    mock_settings.sync_enabled = True
    mock_settings.sync_interval = 60
    wet_mcp.sync._sync_task = None
    start_auto_sync(MagicMock())
    mock_create.assert_called_once()

    # Should not create again
    mock_create.reset_mock()
    wet_mcp.sync._sync_task = MagicMock()
    wet_mcp.sync._sync_task.done.return_value = False
    start_auto_sync(MagicMock())
    mock_create.assert_not_called()


def test_stop_auto_sync():
    mock_task = MagicMock()
    mock_task.done.return_value = False
    wet_mcp.sync._sync_task = mock_task
    stop_auto_sync()
    mock_task.cancel.assert_called_once()
    assert wet_mcp.sync._sync_task is None


@patch("wet_mcp.sync._get_rclone_path")
@patch("wet_mcp.sync._download_rclone")
@patch("wet_mcp.sync.subprocess.run")
@patch("wet_mcp.sync._extract_token")
@patch("wet_mcp.sync.sys.exit")
def test_setup_sync_success(
    mock_exit, mock_extract, mock_run, mock_download, mock_get_path, capsys
):
    mock_get_path.return_value = Path("/rclone")
    mock_run.return_value = subprocess.CompletedProcess(
        args=[], returncode=0, stdout="output"
    )
    mock_extract.return_value = '{"access_token":"token"}'

    setup_sync("drive")

    captured = capsys.readouterr()
    assert "RCLONE_CONFIG_GDRIVE_TOKEN" in captured.out
    assert base64.b64encode(b'{"access_token":"token"}').decode() in captured.out
    mock_exit.assert_not_called()


@patch("wet_mcp.sync._get_rclone_path")
@patch("wet_mcp.sync._download_rclone")
@patch("wet_mcp.sync.subprocess.run")
@patch("wet_mcp.sync.sys.exit")
def test_setup_sync_download_fail(mock_exit, mock_run, mock_download, mock_get_path):
    mock_exit.side_effect = SystemExit
    mock_get_path.return_value = None

    async def async_download():
        return None

    mock_download.side_effect = lambda: (
        async_download()
    )  # wrap it because asyncio.run takes coroutine

    try:
        setup_sync("drive")
    except SystemExit:
        pass
    mock_exit.assert_called_once_with(1)


@patch("wet_mcp.sync._get_rclone_path")
@patch("wet_mcp.sync.subprocess.run")
@patch("wet_mcp.sync.sys.exit")
def test_setup_sync_authorize_fail(mock_exit, mock_run, mock_get_path):
    mock_exit.side_effect = SystemExit
    mock_get_path.return_value = Path("/rclone")
    mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=1)

    try:
        setup_sync("drive")
    except SystemExit:
        pass
    mock_exit.assert_called_once_with(1)
