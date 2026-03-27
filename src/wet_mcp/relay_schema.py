"""Config schema for relay page setup."""

from __future__ import annotations

from typing import Any

RELAY_SCHEMA: dict[str, Any] = {
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
    "sections": [
        {
            "id": "google_drive_sync",
            "label": "Google Drive Sync",
            "description": "Sync docs database across machines via Google Drive",
            "fields": [
                {
                    "key": "SYNC_ENABLED",
                    "label": "Enable Sync",
                    "type": "boolean",
                    "required": False,
                    "helpText": "Enable automatic Google Drive sync for docs database",
                },
                {
                    "key": "GOOGLE_DRIVE_CLIENT_ID",
                    "label": "OAuth Client ID",
                    "type": "text",
                    "placeholder": "123456789.apps.googleusercontent.com",
                    "required": False,
                    "helpText": "Create at console.cloud.google.com/apis/credentials (OAuth 2.0 Client ID, type: TV/Limited Input)",
                },
                {
                    "key": "SYNC_FOLDER",
                    "label": "Drive Folder",
                    "type": "text",
                    "placeholder": "wet-mcp",
                    "required": False,
                    "helpText": "Google Drive folder name for sync (default: wet-mcp)",
                },
            ],
        },
    ],
}
