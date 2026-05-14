"""Tests for the Phase 2 S3 sync backend.

Uses ``moto[s3]`` for an in-memory S3 fixture so tests run offline /
deterministic. Real-bucket integration sits behind the ``integration``
marker (skipped by default per pyproject.toml addopts).

Covers:
- ``push`` writes docs.db to ``<prefix>/docs.db`` exactly.
- ``pull`` returns a temp Path with the bucket bytes; ``None`` when
  the remote has no docs.db yet.
- Custom ``endpoint_url`` is forwarded to boto3 (R2 / B2 / MinIO path).
- ``health_check`` returns False on missing bucket.
- Error paths: ClientError on put/get/list returns False / None
  instead of propagating (so the auto-sync loop never crashes).
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import boto3
import pytest
from moto import mock_aws

from wet_mcp.sync.s3 import S3Backend, _docs_key

_BUCKET = "wet-test-bucket"
_PREFIX = "docs/"


@pytest.fixture
def s3_client() -> Iterator[object]:
    """Yield a moto-backed boto3 S3 client + create the test bucket."""
    with mock_aws():
        client = boto3.client("s3", region_name="us-east-1")
        client.create_bucket(Bucket=_BUCKET)
        yield client


@pytest.fixture
def backend(s3_client) -> S3Backend:  # noqa: ARG001 - s3_client patches boto3
    return S3Backend(
        bucket=_BUCKET,
        region="us-east-1",
        access_key_id="testing",
        secret_access_key="testing",
        prefix=_PREFIX,
    )


@pytest.fixture
def db_file(tmp_path: Path) -> Path:
    """Create a local docs.db stand-in with deterministic bytes."""
    p = tmp_path / "docs.db"
    p.write_bytes(b"SQLite format 3\x00fake-db-content")
    return p


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def test_docs_key_format() -> None:
    assert _docs_key("docs/") == "docs/docs.db"
    assert _docs_key("docs") == "docs/docs.db"
    # Strips trailing slashes consistently.
    assert _docs_key("docs//") == "docs/docs.db"


# ---------------------------------------------------------------------------
# push / pull
# ---------------------------------------------------------------------------


async def test_push_docs_db_to_s3(backend, db_file, s3_client) -> None:
    """``push`` writes the exact file bytes to <prefix>/docs.db."""
    ok = await backend.push(db_file)
    assert ok is True

    obj = s3_client.get_object(Bucket=_BUCKET, Key="docs/docs.db")
    assert obj["Body"].read() == db_file.read_bytes()


async def test_push_overwrites_existing_key(backend, db_file, tmp_path) -> None:
    """``push`` is overwrite-on-write (last-write-wins semantics)."""
    await backend.push(db_file)

    # Mutate local file and re-push.
    db_file.write_bytes(b"v2-content")
    ok = await backend.push(db_file)
    assert ok is True

    pulled = await backend.pull(tmp_path / "docs.db")
    assert pulled is not None
    assert pulled.read_bytes() == b"v2-content"


async def test_pull_docs_db_from_s3(backend, db_file, tmp_path) -> None:
    """``pull`` downloads the bucket object to a temp path."""
    await backend.push(db_file)

    local_target = tmp_path / "docs.db"
    pulled = await backend.pull(local_target)
    assert pulled is not None
    assert pulled.read_bytes() == db_file.read_bytes()
    # Temp path lives under ``<parent>/sync_temp/`` per spec.
    assert pulled.parent.name == "sync_temp"


async def test_pull_empty_bucket_returns_none(backend, tmp_path) -> None:
    """No remote docs.db yet -> pull returns None (fresh-backend signal)."""
    assert await backend.pull(tmp_path / "docs.db") is None


# ---------------------------------------------------------------------------
# health_check + endpoint propagation
# ---------------------------------------------------------------------------


async def test_health_check_returns_true_on_existing_bucket(backend) -> None:
    assert await backend.health_check() is True


async def test_health_check_returns_false_on_missing_bucket(s3_client) -> None:  # noqa: ARG001
    bad_backend = S3Backend(
        bucket="nonexistent-bucket-zzz",
        region="us-east-1",
        access_key_id="testing",
        secret_access_key="testing",
    )
    assert await bad_backend.health_check() is False


def test_custom_endpoint_passed_to_boto3() -> None:
    """R2 / B2 / MinIO endpoint forwarded so boto3 hits the right host."""
    with mock_aws():
        backend = S3Backend(
            bucket="bucket",
            region="auto",
            access_key_id="k",
            secret_access_key="s",
            endpoint_url="https://accountid.r2.cloudflarestorage.com",
        )
        assert backend._client.meta.endpoint_url == (
            "https://accountid.r2.cloudflarestorage.com"
        )


def test_supports_oauth_setup_is_false() -> None:
    """S3 uses operator-provisioned static credentials (no OAuth)."""
    with mock_aws():
        backend = S3Backend(
            bucket="b",
            region="us-east-1",
            access_key_id="k",
            secret_access_key="s",
        )
        assert backend.supports_oauth_setup is False


# ---------------------------------------------------------------------------
# Error paths (return False / None on ClientError)
# ---------------------------------------------------------------------------


async def test_push_returns_false_on_client_error() -> None:
    """ClientError on put_object -> False (loop continues)."""
    from unittest.mock import MagicMock

    from botocore.exceptions import ClientError

    with mock_aws():
        backend = S3Backend(
            bucket=_BUCKET,
            region="us-east-1",
            access_key_id="t",
            secret_access_key="t",
        )
        backend._client = MagicMock()
        backend._client.put_object.side_effect = ClientError(
            {"Error": {"Code": "AccessDenied", "Message": "no perm"}},
            "PutObject",
        )

        # Create a real local file so read_bytes succeeds before the put.
        import tempfile

        with tempfile.NamedTemporaryFile(delete=False) as tf:
            tf.write(b"x")
            p = Path(tf.name)
        try:
            assert await backend.push(p) is False
        finally:
            p.unlink(missing_ok=True)


async def test_pull_returns_none_on_client_error(tmp_path) -> None:
    """Non-NoSuchKey ClientError -> None (loop continues)."""
    from unittest.mock import MagicMock

    from botocore.exceptions import ClientError

    with mock_aws():
        backend = S3Backend(
            bucket=_BUCKET,
            region="us-east-1",
            access_key_id="t",
            secret_access_key="t",
        )
        backend._client = MagicMock()
        backend._client.get_object.side_effect = ClientError(
            {"Error": {"Code": "AccessDenied"}}, "GetObject"
        )

        assert await backend.pull(tmp_path / "docs.db") is None


async def test_pull_returns_none_on_no_such_key(tmp_path) -> None:
    """``NoSuchKey`` is the expected fresh-bucket signal -> None."""
    from unittest.mock import MagicMock

    from botocore.exceptions import ClientError

    with mock_aws():
        backend = S3Backend(
            bucket=_BUCKET,
            region="us-east-1",
            access_key_id="t",
            secret_access_key="t",
        )
        backend._client = MagicMock()
        backend._client.get_object.side_effect = ClientError(
            {"Error": {"Code": "NoSuchKey"}}, "GetObject"
        )

        assert await backend.pull(tmp_path / "docs.db") is None


async def test_health_check_returns_false_on_generic_exception() -> None:
    """Non-ClientError (e.g. timeout) -> False, not exception."""
    from unittest.mock import MagicMock

    with mock_aws():
        backend = S3Backend(
            bucket=_BUCKET,
            region="us-east-1",
            access_key_id="t",
            secret_access_key="t",
        )
        backend._client = MagicMock()
        backend._client.head_bucket.side_effect = TimeoutError("network down")
        assert await backend.health_check() is False
