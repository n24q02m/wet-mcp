from mcp_core.storage.backends import InMemoryBackend


def test_store_for_sub_routes_through_selected_backend(monkeypatch):
    monkeypatch.setenv("CREDENTIAL_SECRET", "k")
    mem = InMemoryBackend()
    monkeypatch.setattr("wet_mcp.credential_state.backend_from_env", lambda: mem)
    from wet_mcp.credential_state import read_for_sub, store_for_sub

    store_for_sub("user1", {"JINA_AI_API_KEY": "key1"})
    assert mem.get("wet/subs/user1/config") is not None
    assert read_for_sub("user1") == {"JINA_AI_API_KEY": "key1"}
