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
    from wet_mcp.db_cf import DocsDBCfBackend
    from wet_mcp.server import make_docs_db

    db = make_docs_db()
    assert isinstance(db, DocsDBCfBackend)
