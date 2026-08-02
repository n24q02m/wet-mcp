"""``config(action="status")`` must describe the docs store actually in use.

The status payload is what an operator reads before they go looking for the
data: they copy ``database.path`` into a backup script, an rsync, a `sqlite3`
session. When ``DOCS_DB_BACKEND=cf-d1`` the docs live in Cloudflare D1 +
Vectorize and no local file is opened at all, so printing
``~/.wet-mcp/docs.db`` there is not merely unhelpful, it points the operator at
a file whose contents are unrelated to what the server is serving.
"""

import json
from unittest.mock import patch

import pytest


@pytest.fixture
def _status_backends():
    """Keep the status call off the real embedder/reranker singletons."""
    with (
        patch("wet_mcp.embedder.get_backend", return_value=None),
        patch("wet_mcp.reranker.get_reranker", return_value=None),
    ):
        yield


async def test_status_on_cf_d1_does_not_claim_a_local_docs_file(
    monkeypatch, _status_backends
):
    """cf-d1 opens no local file, so ``path`` must not name one."""
    monkeypatch.setenv("DOCS_DB_BACKEND", "cf-d1")
    from wet_mcp.server import _handle_config_status

    status = await _handle_config_status()

    assert status["database"]["path"] is None


async def test_status_names_the_active_docs_backend(monkeypatch, _status_backends):
    """The operator can tell D1 from SQLite without reading the container env."""
    from wet_mcp.server import _handle_config_status

    monkeypatch.setenv("DOCS_DB_BACKEND", "cf-d1")
    assert (await _handle_config_status())["database"]["backend"] == "cf-d1"

    monkeypatch.setenv("DOCS_DB_BACKEND", "sqlite")
    assert (await _handle_config_status())["database"]["backend"] == "sqlite"


async def test_status_on_sqlite_still_reports_the_local_path(
    monkeypatch, _status_backends
):
    """The default backend keeps the field every existing reader expects."""
    monkeypatch.delenv("DOCS_DB_BACKEND", raising=False)
    from wet_mcp.config import settings
    from wet_mcp.server import _handle_config_status

    monkeypatch.setattr(settings, "docs_db_backend", "sqlite", raising=False)

    status = await _handle_config_status()

    assert status["database"]["path"] == str(settings.get_db_path())


async def test_status_on_cf_d1_leaks_no_d1_credential_or_identifier(
    monkeypatch, _status_backends
):
    """Naming the backend must not drag the D1 wiring into the payload.

    ``config`` is an operator-facing tool, but its output gets pasted into bug
    reports and agent transcripts. Tokens are secrets outright; the account and
    database ids in ``MCP_D1_BASE_URL`` name the target a leaked token would
    open. Neither is needed to answer "where are my docs".
    """
    monkeypatch.setenv("DOCS_DB_BACKEND", "cf-d1")
    from wet_mcp.config import settings
    from wet_mcp.server import _handle_config_status

    monkeypatch.setattr(settings, "mcp_d1_token", "SECRET-D1-TOKEN", raising=False)
    monkeypatch.setattr(
        settings, "mcp_vectorize_token", "SECRET-VECTORIZE-TOKEN", raising=False
    )
    monkeypatch.setattr(
        settings,
        "mcp_d1_base_url",
        "https://api.cloudflare.com/client/v4/accounts/ACCTID123/d1/database/DBID456",
        raising=False,
    )
    monkeypatch.setattr(settings, "mcp_vectorize_idx", "IDXNAME789", raising=False)

    dumped = json.dumps(await _handle_config_status(), default=str)

    for secret in (
        "SECRET-D1-TOKEN",
        "SECRET-VECTORIZE-TOKEN",
        "ACCTID123",
        "DBID456",
        "IDXNAME789",
    ):
        assert secret not in dumped
