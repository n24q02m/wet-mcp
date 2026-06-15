def test_cf_fields_from_env(monkeypatch):
    monkeypatch.setenv("PUBLIC_URL", "https://wet.n24q02m.com")
    monkeypatch.setenv("MCP_STORAGE_BACKEND", "cf-kv")
    monkeypatch.setenv("MCP_KV_BASE_URL", "http://kv.internal")
    monkeypatch.setenv("DOCS_DB_BACKEND", "cf-d1")
    monkeypatch.setenv("SEARCH_BACKEND", "tavily")
    monkeypatch.setenv("TAVILY_API_KEY", "tav")
    from wet_mcp.config import Settings

    s = Settings()
    assert s.public_url == "https://wet.n24q02m.com"
    assert s.mcp_storage_backend == "cf-kv"
    assert s.mcp_kv_base_url == "http://kv.internal"
    assert s.docs_db_backend == "cf-d1"
    assert s.search_backend == "tavily"
    assert s.tavily_api_key == "tav"


def test_cf_fields_default_local(monkeypatch):
    for v in ("MCP_STORAGE_BACKEND", "DOCS_DB_BACKEND", "SEARCH_BACKEND"):
        monkeypatch.delenv(v, raising=False)
    from wet_mcp.config import Settings

    s = Settings()
    assert s.mcp_storage_backend == "local"
    assert s.docs_db_backend == "sqlite"
    assert s.search_backend == "searxng"
