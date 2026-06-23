"""Config schema for relay page setup.

Tasks are model chains (order = litellm fallback). Provider key fields are
``derived`` -- the relay widget surfaces them automatically for the providers
the chosen models reference. ``GITHUB_TOKEN`` is a plain (non-derived) key:
it is NOT a model-provider key, just an optional GitHub API rate-limit bump
for library docs discovery.
"""

from __future__ import annotations

from typing import Any

# model-chain tasks (embedding/rerank/chat) carry NO hardcoded suggestions: the
# relay widget's dropdown is fully catalog-driven (live Jina + normalized litellm
# from mcp-core). Only the search-chain below keeps a curated list, since its
# named backends are not litellm models and have no catalog to search.
# Named search backends (no model-prefix inference; resolved via providerKeys).
_SEARCH_BACKENDS = ["searxng", "tavily", "brave", "exa"]


def _key_field(key: str, label: str, ph: str, url: str) -> dict[str, Any]:
    return {
        "key": key,
        "label": label,
        "type": "password",
        "placeholder": ph,
        "helpUrl": url,
        "helpText": "Multiple keys: comma-separate for automatic rotation on rate-limit.",
        "derived": True,
        "required": False,
    }


RELAY_SCHEMA: dict[str, Any] = {
    "server": "wet-mcp",
    "displayName": "Web Extended Toolkit",
    "description": (
        "Pick models per task (order = fallback). Leave a task empty for "
        "local ONNX (embedding/rerank) — LLM features need at least one model. "
        "Key fields appear automatically for the providers your models use. "
        "Search runs local SearXNG by default; add cloud providers "
        "(Tavily/Brave/Exa) for a fallback chain. Extraction is always local."
    ),
    "fields": [
        {
            "key": "EMBEDDING_MODELS",
            "label": "Embedding models",
            "type": "model-chain",
            "task": "embedding",
            "hasLocal": True,
            "placeholder": "add embedding model…",
        },
        {
            "key": "RERANK_MODELS",
            "label": "Rerank models",
            "type": "model-chain",
            "task": "rerank",
            "hasLocal": True,
            "placeholder": "add rerank model…",
        },
        {
            "key": "LLM_MODELS",
            "label": "LLM models",
            "type": "model-chain",
            "task": "chat",
            "hasLocal": False,
            "placeholder": "add LLM model…",
        },
        {
            "key": "SEARCH_BACKENDS",
            "label": "Search providers",
            "type": "search-chain",
            "task": "search",
            "suggestedModels": _SEARCH_BACKENDS,
            "providerKeys": {
                "searxng": "SEARXNG_URL",
                "tavily": "TAVILY_API_KEY",
                "brave": "BRAVE_API_KEY",
                "exa": "EXA_API_KEY",
            },
            "hasLocal": True,
            "noun": "providers",
            "localLabel": "local SearXNG",
            "placeholder": "add search provider…",
        },
        _key_field(
            "JINA_AI_API_KEY", "Jina AI API Key", "jina_...", "https://jina.ai/api-key"
        ),
        _key_field(
            "GEMINI_API_KEY",
            "Gemini API Key",
            "AIza...",
            "https://aistudio.google.com/apikey",
        ),
        _key_field(
            "OPENAI_API_KEY",
            "OpenAI API Key",
            "sk-...",
            "https://platform.openai.com/api-keys",
        ),
        _key_field(
            "COHERE_API_KEY",
            "Cohere API Key",
            "co-...",
            "https://dashboard.cohere.com/api-keys",
        ),
        _key_field(
            "ANTHROPIC_API_KEY",
            "Anthropic API Key",
            "sk-ant-...",
            "https://console.anthropic.com/settings/keys",
        ),
        _key_field("XAI_API_KEY", "xAI API Key", "xai-...", "https://console.x.ai/"),
        _key_field(
            "TAVILY_API_KEY",
            "Tavily API Key",
            "tvly-...",
            "https://app.tavily.com/home",
        ),
        _key_field(
            "BRAVE_API_KEY",
            "Brave Search API Key",
            "BSA...",
            "https://api-dashboard.search.brave.com/app/keys",
        ),
        _key_field(
            "EXA_API_KEY", "Exa API Key", "exa_...", "https://dashboard.exa.ai/api-keys"
        ),
        {
            # SearXNG is a named backend (not a model-prefix provider): selecting
            # it in the search chain derives this field via providerKeys so the
            # user can point at an external instance. Blank -> auto-started local
            # SearXNG. Optional basic-auth via env SEARXNG_AUTH_USER/PASS.
            "key": "SEARXNG_URL",
            "label": "SearXNG URL (external instance)",
            "type": "url",
            "placeholder": "https://searxng.example.com",
            "helpText": (
                "Point at an external SearXNG. Leave blank to use the local "
                "auto-started instance. Basic-auth (if any): set env "
                "SEARXNG_AUTH_USER / SEARXNG_AUTH_PASS."
            ),
            "derived": True,
            "required": False,
        },
        {
            "key": "GITHUB_TOKEN",
            "label": "GitHub Personal Access Token",
            "type": "password",
            "placeholder": "ghp_...",
            "helpUrl": "https://github.com/settings/tokens",
            "helpText": "Optional. Bumps GitHub API rate limit (60->5000 req/hr) for library docs discovery.",
            "required": False,
        },
        {
            "key": "CAPSOLVER_API_KEY",
            "label": "CapSolver API Key",
            "type": "password",
            "placeholder": "CAP-...",
            "helpUrl": "https://dashboard.capsolver.com/",
            "helpText": "Optional. Solves reCAPTCHA / Cloudflare Turnstile on protected pages during extraction.",
            "required": False,
        },
    ],
    "capabilityInfo": [
        {
            "label": "Search",
            "priority": "configurable",
            "description": (
                "Web search. Local SearXNG auto-starts by default (no key); add "
                "cloud providers (Tavily/Brave/Exa) above for a fallback chain."
            ),
        },
        {
            "label": "Extraction",
            "priority": "Built-in (httpx + readability)",
            "description": "Content extraction from URLs. No API key needed.",
        },
        {
            "label": "Embedding",
            "priority": "configurable",
            "description": "Vector embeddings for docs search. Empty = local Qwen3-Embedding ONNX.",
        },
        {
            "label": "Reranking",
            "priority": "configurable",
            "description": "Re-ranks search results for accuracy. Empty = local Qwen3-Reranker ONNX.",
        },
        {
            "label": "LLM",
            "priority": "configurable",
            "description": "Structured extraction. Empty = these features are limited.",
        },
    ],
}
