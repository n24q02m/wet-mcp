import pytest


def test_docs_db_selection_sqlite(monkeypatch, tmp_path):
    monkeypatch.delenv("DOCS_DB_BACKEND", raising=False)
    # Isolate the docs DB to tmp_path so the B2 model-identity guard does not
    # trip on a real ~/.wet-mcp/docs.db left stamped by another test/run. The
    # sqlite path of make_docs_db() reads the Settings singleton, so swap it for
    # a fresh instance pointing at tmp_path.
    import wet_mcp.config as config_mod
    from wet_mcp.config import Settings

    monkeypatch.setattr(
        config_mod, "settings", Settings(docs_db_path=str(tmp_path / "docs.db"))
    )
    from wet_mcp.db import DocsDB
    from wet_mcp.server import make_docs_db

    db = make_docs_db()
    assert isinstance(db, DocsDB)


def test_docs_db_selection_cf_d1(cf_env):
    """cf-d1 either hands back a complete backend or refuses to start.

    Asserted as the invariant rather than as today's method count so this
    passes unchanged once DocsDBCfBackend implements the rest of DocsDB.
    """
    from wet_mcp.db_cf import DocsDBCfBackend
    from wet_mcp.server import _missing_docs_db_methods, make_docs_db

    missing = _missing_docs_db_methods(DocsDBCfBackend)
    if not missing:
        assert isinstance(make_docs_db(), DocsDBCfBackend)
        return

    with pytest.raises(RuntimeError) as excinfo:
        make_docs_db()
    for name in missing:
        assert name in str(excinfo.value)


def test_docs_db_cf_backend_missing_methods_refuses_to_start(cf_env, monkeypatch):
    """A partial backend must fail at construction, not halfway through indexing.

    ``_background_index_and_search`` calls ``add_chunks`` and then
    ``mark_version_indexed``; with the second one absent the write lands, the
    AttributeError is swallowed by the task's ``except Exception`` logger, and
    the version stays un-indexed forever. Startup is the only place that
    failure is still cheap and legible.
    """
    import wet_mcp.db_cf as db_cf_mod
    from wet_mcp.server import make_docs_db

    class _PartialBackend:
        """Implements add_chunks but not the marks that follow it."""

        def __init__(self, *args, **kwargs) -> None:
            pass

        def add_chunks(self, *args, **kwargs) -> int:
            return 0

        def search(self, *args, **kwargs) -> list:
            return []

    monkeypatch.setattr(db_cf_mod, "DocsDBCfBackend", _PartialBackend)

    with pytest.raises(RuntimeError) as excinfo:
        make_docs_db()

    message = str(excinfo.value)
    assert "_PartialBackend" in message
    # The point of the guard is that it names what is missing.
    assert "mark_version_indexed" in message
    assert "upsert_library" in message
