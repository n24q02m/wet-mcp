import shutil
import subprocess

import pytest


@pytest.mark.skipif(shutil.which("docker") is None, reason="docker not installed")
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
    )
    assert r.returncode == 0, r.stderr
    assert "TRANSPORT_MODE=http" in r.stdout or "TRANSPORT_MODE: http" in r.stdout


@pytest.mark.skipif(shutil.which("docker") is None, reason="docker not installed")
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
    )
    assert r.returncode == 0, r.stderr
    assert "cf-kv" in r.stdout
