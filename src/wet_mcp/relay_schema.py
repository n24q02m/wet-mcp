"""Config schema for relay page setup."""

RELAY_SCHEMA = {
    "server": "wet-mcp",
    "displayName": "Web Extended Toolkit",
    "modes": [
        {
            "id": "local",
            "label": "Local (Default)",
            "description": "Uses built-in ONNX models. No API keys needed.",
            "fields": [],
        },
        {
            "id": "proxy",
            "label": "LiteLLM Proxy",
            "description": "Use a LiteLLM proxy for LLM and embedding",
            "fields": [
                {
                    "key": "LITELLM_PROXY_URL",
                    "label": "Proxy URL",
                    "type": "url",
                    "placeholder": "https://litellm.example.com",
                },
                {
                    "key": "LITELLM_PROXY_KEY",
                    "label": "Proxy API Key",
                    "type": "password",
                    "required": False,
                },
            ],
        },
        {
            "id": "sdk",
            "label": "Direct API Keys",
            "description": "Use API keys directly (OpenAI, Gemini, etc.)",
            "fields": [
                {
                    "key": "API_KEYS",
                    "label": "API Keys",
                    "type": "password",
                    "placeholder": "GEMINI_API_KEY:AIza...",
                    "helpText": "Format: PROVIDER_KEY:value (comma-separated for multiple)",
                },
            ],
        },
    ],
}
