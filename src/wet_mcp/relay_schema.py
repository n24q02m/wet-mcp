"""Config schema for relay page setup.

Tasks are model chains (order = litellm fallback). Provider key fields are
``derived`` -- the relay widget surfaces them automatically for the providers
the chosen models reference. ``GITHUB_TOKEN`` is a plain (non-derived) key:
it is NOT a model-provider key, just an optional GitHub API rate-limit bump
for library docs discovery.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

_EMBEDDING_SUGGESTED = [
    "jina_ai/jina-embeddings-v5-text-small",
    "gemini/gemini-embedding-001",
    "openai/text-embedding-3-large",
    "cohere/embed-multilingual-v3.0",
]
_RERANK_SUGGESTED = ["jina_ai/jina-reranker-v3", "cohere/rerank-v3.5"]
_LLM_SUGGESTED = [
    "gemini/gemini-3-flash-preview",
    "openai/gpt-5.4-mini-2026-03-17",
    "anthropic/claude-haiku-4-5",
    "xai/grok-4-fast",
]


def _key_field(key: str, label: str, ph: str, url: str) -> dict[str, Any]:
    return {
        "key": key,
        "label": label,
        "type": "password",
        "placeholder": ph,
        "helpUrl": url,
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
        "Search + extraction are always local (no key needed)."
    ),
    "fields": [
        {
            "key": "EMBEDDING_MODELS",
            "label": "Embedding models",
            "type": "model-chain",
            "task": "embedding",
            "suggestedModels": _EMBEDDING_SUGGESTED,
            "hasLocal": True,
            "placeholder": "add embedding model…",
        },
        {
            "key": "RERANK_MODELS",
            "label": "Rerank models",
            "type": "model-chain",
            "task": "rerank",
            "suggestedModels": _RERANK_SUGGESTED,
            "hasLocal": True,
            "placeholder": "add rerank model…",
        },
        {
            "key": "LLM_MODELS",
            "label": "LLM models",
            "type": "model-chain",
            "task": "chat",
            "suggestedModels": _LLM_SUGGESTED,
            "hasLocal": False,
            "placeholder": "add LLM model…",
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
        {
            "key": "GITHUB_TOKEN",
            "label": "GitHub Personal Access Token",
            "type": "password",
            "placeholder": "ghp_...",
            "helpUrl": "https://github.com/settings/tokens",
            "helpText": "Optional. Bumps GitHub API rate limit (60->5000 req/hr) for library docs discovery.",
            "required": False,
        },
    ],
    "capabilityInfo": [
        {
            "label": "Search",
            "priority": "SearXNG (auto-start local)",
            "description": "Web search via SearXNG. Auto-starts locally, no API key needed.",
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


class ConfigData(BaseModel):
    token: str = Field(..., description="The API token")
