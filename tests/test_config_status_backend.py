"""``config(action="status")`` must describe the docs store actually in use.

The status payload is what an operator reads before they go looking for the
data: they copy ``database.path`` into a backup script, an rsync, a `sqlite3`
session. When ``DOCS_DB_BACKEND=cf-d1`` the docs live in Cloudflare D1 +
Vectorize and no local file is opened at all, so printing
``~/.wet-mcp/docs.db`` there is not merely unhelpful, it points the operator at
a file whose contents are unrelated to what the server is serving.
"""

import json
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def _status_backends():
    """Keep the status call off the real embedder/reranker singletons."""
    with (
        patch("wet_mcp.embedder.get_backend", return_value=None),
        patch("wet_mcp.reranker.get_reranker", return_value=None),
    ):
        yield


@pytest.fixture
def _built_backend(monkeypatch):
    """Run the real ``make_docs_db`` selector, stubbing only its leaf builders.

    The branch decision inside ``make_docs_db`` stays untouched -- that is the
    thing under observation. What gets replaced is strictly what would demand a
    disk file, a D1 account or the network:

    * ``DocsDB.__init__`` on the real class (not the name ``server`` holds), so
      ``_missing_docs_db_methods`` can still read ``vars(DocsDB)`` as its
      contract while construction opens nothing.
    * ``DocsDBCfBackend`` -> a ``MagicMock`` instance, whose auto-created
      attributes are all callable, so the missing-method guard passes whatever
      state the real cf backend is in. This test is about the selector, not
      about that backend's surface.

    Returns a list that records ``"sqlite"`` / ``"cf-d1"`` per construction.
    """
    from wet_mcp.db import DocsDB

    built: list[str] = []

    def _sqlite_init(self, *args, **kwargs):
        built.append("sqlite")

    def _cf_build(*args, **kwargs):
        built.append("cf-d1")
        return MagicMock()

    monkeypatch.setattr(DocsDB, "__init__", _sqlite_init)
    monkeypatch.setattr("wet_mcp.db_cf.DocsDBCfBackend", _cf_build)
    monkeypatch.setattr(
        "mcp_core.storage.d1.d1_backend_from_env", lambda *a, **k: MagicMock()
    )
    monkeypatch.setattr(
        "mcp_core.storage.vectorize.vectorize_backend_from_env",
        lambda *a, **k: MagicMock(),
    )
    return built


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


@pytest.mark.parametrize(
    "raw",
    [
        "cf-d1",
        "sqlite",
        None,
        "CF-D1",
        " cf-d1 ",
        "",
        "postgres",
    ],
)
async def test_status_label_agrees_with_the_backend_make_docs_db_builds(
    raw, monkeypatch, _built_backend, _status_backends
):
    """The status label and the constructed store must never disagree.

    ``_active_docs_backend`` is documented as a byte-for-byte mirror of the
    selector in ``make_docs_db``, but a docstring is a promise nobody checks:
    add ``.strip().lower()`` to one side and the mirror cracks in silence --
    ``make_docs_db`` builds D1 while ``config status`` keeps printing a local
    path, which is exactly the bug this module exists to prevent.

    The dirty spellings carry the weight here. ``"CF-D1"`` and ``" cf-d1 "``
    are the inputs where a one-sided normalization changes one branch and not
    the other, so they are the only ones that can catch the drift; the clean
    values would stay green through it.
    """
    from wet_mcp.server import _active_docs_backend, _handle_config_status, make_docs_db

    if raw is None:
        monkeypatch.delenv("DOCS_DB_BACKEND", raising=False)
        from wet_mcp.config import settings

        monkeypatch.setattr(settings, "docs_db_backend", "sqlite", raising=False)
    else:
        monkeypatch.setenv("DOCS_DB_BACKEND", raw)

    make_docs_db()
    assert _built_backend, "make_docs_db built nothing; the stubs missed a branch"
    built_is_cf = _built_backend[-1] == "cf-d1"

    assert (_active_docs_backend() == "cf-d1") == built_is_cf

    status = await _handle_config_status()
    assert (status["database"]["path"] is None) == built_is_cf
    assert (status["database"]["backend"] == "cf-d1") == built_is_cf
