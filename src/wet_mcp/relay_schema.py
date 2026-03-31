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
            "helpText": "Embedding + Reranking (highest priority for both).",
            "required": False,
        },
        {
            "key": "GEMINI_API_KEY",
            "label": "Gemini API Key",
            "type": "password",
            "placeholder": "AIza...",
            "helpUrl": "https://aistudio.google.com/apikey",
            "helpText": "Embedding + LLM/Vision. Free tier available.",
            "required": False,
        },
        {
            "key": "OPENAI_API_KEY",
            "label": "OpenAI API Key",
            "type": "password",
            "placeholder": "sk-...",
            "helpUrl": "https://platform.openai.com/api-keys",
            "helpText": "Embedding + LLM/Vision (lower priority than Gemini).",
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
            "key": "GOOGLE_DRIVE_CLIENT_ID",
            "label": "Google Drive OAuth Client ID",
            "type": "text",
            "placeholder": "123456789.apps.googleusercontent.com",
            "helpUrl": "https://console.cloud.google.com/apis/credentials",
            "helpText": "For syncing docs database across machines. Create OAuth 2.0 Client ID (type: TV/Limited Input).",
            "required": False,
        },
    ],
    "capabilityInfo": [
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
            "label": "LLM / Vision",
            "priority": "Gemini > OpenAI",
            "description": "Image analysis and keyword extraction. Without a key, the MCP client/agent handles images directly.",
        },
    ],
}
