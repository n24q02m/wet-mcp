"""Không còn tham chiếu đến tên gói cũ, kể cả trong chuỗi và Dockerfile."""

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEST_FILE = Path(__file__).resolve().relative_to(ROOT).as_posix()

# CHANGELOG ghi lại lịch sử; tên gói cũ ở đó là đúng và phải giữ nguyên.
ALLOWED = {"CHANGELOG.md"}
# Tên biến cũ được đọc có chủ ý để không làm vỡ cấu hình người dùng cũ.
ALLOWED_LINES = ("QWEN3_EMBED_CACHE_PATH",)


def _tracked_hits(pattern: str) -> list[str]:
    result = subprocess.run(
        ["git", "grep", "-n", pattern],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    return [
        line
        for line in result.stdout.splitlines()
        if line
        and not line.startswith(f"{TEST_FILE}:")
        and not any(line.startswith(f"{name}:") for name in ALLOWED)
        and not any(token in line for token in ALLOWED_LINES)
    ]


def test_no_module_reference_remains():
    hits = _tracked_hits("qwen3_embed")
    assert not hits, "stale module name:\n" + "\n".join(hits)


def test_no_distribution_reference_remains():
    hits = _tracked_hits("qwen3-embed")
    assert not hits, "stale distribution name:\n" + "\n".join(hits)
