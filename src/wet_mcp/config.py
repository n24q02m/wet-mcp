"""Configuration settings for WET MCP Server."""

import os
from pathlib import Path

from pydantic_settings import BaseSettings


def _default_data_dir() -> Path:
    """Get default data directory (~/.wet-mcp/)."""
    return Path.home() / ".wet-mcp"


class Settings(BaseSettings):
    """WET MCP Server configuration.

    Environment variables:
    - SEARXNG_URL: SearXNG instance URL (default: http://localhost:8080)
    - API_KEYS: Provider API keys (format: ENV_VAR:key,ENV_VAR:key)
    - EMBEDDING_MODEL: LiteLLM embedding model (auto-detected if not set)
    - EMBEDDING_DIMS: Embedding dimensions (0 = auto-detect, default 768)
    - SYNC_ENABLED: Enable rclone sync (default: false)
    - SYNC_REMOTE: Rclone remote name (e.g., "gdrive")
    - SYNC_FOLDER: Remote folder name (default: "wet-mcp")
    - SYNC_INTERVAL: Auto-sync interval in seconds (0 = manual only)
    """

    # SearXNG
    searxng_url: str = "http://localhost:8080"
    searxng_timeout: int = 30

    # Crawler
    crawler_headless: bool = True
    crawler_timeout: int = 60

    # SearXNG Management
    wet_auto_searxng: bool = True
    wet_searxng_port: int = 8080

    # Tool execution timeout (seconds, 0 = no timeout)
    tool_timeout: int = 120

    # Media
    download_dir: str = "~/.wet-mcp/downloads"

    # Media Analysis (LiteLLM)
    api_keys: str | None = None  # provider:key,provider:key
    llm_models: str = "gemini/gemini-3-flash-preview"  # provider/model (fallback chain)
    llm_temperature: float | None = None

    # Cache (web operations)
    wet_cache: bool = True  # Enable/disable web cache
    cache_dir: str = ""  # Cache database directory, default: ~/.wet-mcp

    # Docs storage
    docs_db_path: str = ""  # Default: ~/.wet-mcp/docs.db

    # Embedding (for docs vector search, optional)
    embedding_model: str = ""  # LiteLLM format, auto-detect if empty
    embedding_dims: int = 0  # 0 = use server default (768)

    # Docs sync (rclone)
    sync_enabled: bool = False
    sync_remote: str = ""  # rclone remote name (e.g., "gdrive")
    sync_folder: str = "wet-mcp"  # remote folder
    sync_interval: int = 0  # seconds, 0 = manual only

    # Logging
    log_level: str = "INFO"

    model_config = {"env_prefix": "", "case_sensitive": False}

    # --- Path helpers (aligned with mnemo-mcp) ---

    def get_data_dir(self) -> Path:
        """Get data directory.

        Uses CACHE_DIR if set, otherwise ~/.wet-mcp/.
        """
        if self.cache_dir:
            return Path(self.cache_dir).expanduser()
        return _default_data_dir()

    def get_db_path(self) -> Path:
        """Get resolved docs database path."""
        if self.docs_db_path:
            return Path(self.docs_db_path).expanduser()
        return self.get_data_dir() / "docs.db"

    def get_cache_db_path(self) -> Path:
        """Get resolved web cache database path."""
        return self.get_data_dir() / "cache.db"

    # --- API key management ---

    # LiteLLM uses different env vars for embeddings vs completions
    _ENV_ALIASES: dict[str, str] = {
        "GOOGLE_API_KEY": "GEMINI_API_KEY",
    }

    def setup_api_keys(self) -> dict[str, list[str]]:
        """Parse API_KEYS and set env vars for LiteLLM.

        Format: "GOOGLE_API_KEY:AIza...,OPENAI_API_KEY:sk-..."

        Also sets aliases (e.g., GOOGLE_API_KEY -> GEMINI_API_KEY)
        because LiteLLM embedding uses GEMINI_API_KEY for gemini/ models.

        Returns:
            Dict mapping env var name to list of API keys.
        """
        if not self.api_keys:
            return {}

        keys_by_env: dict[str, list[str]] = {}

        for pair in self.api_keys.split(","):
            pair = pair.strip()
            if ":" not in pair:
                continue

            env_var, key = pair.split(":", 1)
            env_var = env_var.strip()
            key = key.strip()

            if not key:
                continue

            keys_by_env.setdefault(env_var, []).append(key)

        # Set first key of each env var (LiteLLM reads from env)
        for env_var, keys in keys_by_env.items():
            if keys:
                os.environ[env_var] = keys[0]
                # Set alias if defined (e.g., GOOGLE_API_KEY -> GEMINI_API_KEY)
                alias = self._ENV_ALIASES.get(env_var)
                if alias and alias not in os.environ:
                    os.environ[alias] = keys[0]

        return keys_by_env

    # --- Embedding resolution ---

    def resolve_embedding_model(self) -> str | None:
        """Return explicit EMBEDDING_MODEL or None for auto-detect.

        If EMBEDDING_MODEL is set explicitly, return it.
        Otherwise return None -- auto-detection happens in server lifespan
        by trying candidate models via LiteLLM.
        """
        if self.embedding_model:
            return self.embedding_model
        return None

    def resolve_embedding_dims(self) -> int:
        """Return explicit EMBEDDING_DIMS or 0 for auto-detect."""
        return self.embedding_dims


settings = Settings()
