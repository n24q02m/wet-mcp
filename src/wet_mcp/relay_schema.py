"""Config schema for relay page setup."""

from __future__ import annotations

from typing import Any

RELAY_SCHEMA: dict[str, Any] = {
    "server": "wet-mcp",
    "displayName": "Web Extended Toolkit",
    "description": "Enter API keys for cloud capabilities. Leave all empty for pure local mode (ONNX models).",
    "fields": [
        {
            "key": "JINA_AI_API_KEY",
            "label": "Jina AI API Key",
            "type": "password",
            "placeholder": "jina_...",
            "helpUrl": "https://jina.ai/api-key",
            "helpText": "Embedding + Reranking (highest priority cloud provider).",
            "required": False,
        },
        {
            "key": "GEMINI_API_KEY",
            "label": "Gemini API Key",
            "type": "password",
            "placeholder": "AIza...",
            "helpUrl": "https://aistudio.google.com/apikey",
            "helpText": "LLM (structured extraction) + Embedding. Free tier available.",
            "required": False,
        },
        {
            "key": "OPENAI_API_KEY",
            "label": "OpenAI API Key",
            "type": "password",
            "placeholder": "sk-...",
            "helpUrl": "https://platform.openai.com/api-keys",
            "helpText": "LLM + Embedding (lower priority than Gemini).",
            "required": False,
        },
        {
            "key": "COHERE_API_KEY",
            "label": "Cohere API Key",
            "type": "password",
            "placeholder": "co-...",
            "helpUrl": "https://dashboard.cohere.com/api-keys",
            "helpText": "Embedding + Reranking.",
            "required": False,
        },
        {
            "key": "XAI_API_KEY",
            "label": "xAI API Key",
            "type": "password",
            "placeholder": "xai-...",
            "helpUrl": "https://console.x.ai",
            "helpText": "LLM (xAI/Grok).",
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
            "priority": "Jina > Gemini > OpenAI > Cohere > Local ONNX",
            "description": "Vector embeddings for docs search. Local mode uses Qwen3-Embedding (0.6B ONNX).",
        },
        {
            "label": "Reranking",
            "priority": "Jina > Cohere > Local ONNX",
            "description": "Re-ranks search results for accuracy. Local mode uses Qwen3-Reranker (0.6B ONNX).",
        },
        {
            "label": "LLM",
            "priority": "Gemini > OpenAI > xAI",
            "description": "Used for structured extraction. Without a key, these features are limited.",
        },
    ],
}
