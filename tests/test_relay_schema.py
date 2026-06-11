from wet_mcp.relay_schema import RELAY_SCHEMA


def test_has_model_chain_tasks():
    tasks = {
        f.get("task") for f in RELAY_SCHEMA["fields"] if f.get("type") == "model-chain"
    }
    assert tasks == {"embedding", "rerank", "chat"}


def test_key_fields_are_derived():
    derived = {f["key"] for f in RELAY_SCHEMA["fields"] if f.get("derived")}
    assert "GEMINI_API_KEY" in derived and "JINA_AI_API_KEY" in derived


def test_github_token_not_derived_not_chain():
    # GITHUB_TOKEN is a plain rate-limit key, not a model-provider key.
    gh = next(f for f in RELAY_SCHEMA["fields"] if f["key"] == "GITHUB_TOKEN")
    assert gh["type"] == "password"
    assert not gh.get("derived")
    assert gh.get("task") is None


def test_no_hardcoded_priority_strings():
    for cap in RELAY_SCHEMA.get("capabilityInfo", []):
        assert ">" not in cap.get("priority", "")


def test_suggested_models_carry_provider_prefix():
    # Every suggested model must carry a "<provider>/" prefix so the widget
    # derive-keys maps it to the correct key field.
    for f in RELAY_SCHEMA["fields"]:
        if f.get("type") == "model-chain":
            for m in f["suggestedModels"]:
                assert "/" in m, f"suggested model {m!r} lacks a provider prefix"
