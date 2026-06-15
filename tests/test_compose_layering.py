import shutil
import subprocess

import pytest


def _docker_available() -> bool:
    """Docker must be installed AND its daemon reachable.

    A plain ``shutil.which("docker")`` check is not enough: some CI runners
    (e.g. windows-latest) ship the docker CLI on PATH while the daemon is not
    running, so ``docker compose config`` blocks on the daemon connection and
    the test hangs to the pytest timeout instead of skipping. ``docker info``
    contacts the daemon, so a short-timeout probe distinguishes "usable" from
    "CLI present but daemon down".
    """
    if shutil.which("docker") is None:
        return False
    try:
        return (
            subprocess.run(
                ["docker", "info"], capture_output=True, timeout=15
            ).returncode
            == 0
        )
    except (subprocess.TimeoutExpired, OSError):
        return False


_DOCKER = _docker_available()


@pytest.mark.skipif(not _DOCKER, reason="docker daemon not available")
def test_http_overlay_layers_on_base():
    r = subprocess.run(
        [
            "docker",
            "compose",
            "-f",
            "docker-compose.yml",
            "-f",
            "docker-compose.http.yml",
            "config",
        ],
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert r.returncode == 0, r.stderr
    assert "TRANSPORT_MODE=http" in r.stdout or "TRANSPORT_MODE: http" in r.stdout


@pytest.mark.skipif(not _DOCKER, reason="docker daemon not available")
def test_cloudflare_overlay_valid():
    r = subprocess.run(
        [
            "docker",
            "compose",
            "-f",
            "docker-compose.yml",
            "-f",
            "docker-compose.cloudflare.yml",
            "config",
        ],
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert r.returncode == 0, r.stderr
    assert "cf-kv" in r.stdout
