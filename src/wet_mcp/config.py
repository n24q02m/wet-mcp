"""Configuration settings for WET MCP Server."""

import os
from pathlib import Path

from pydantic_settings import BaseSettings


def _default_data_dir() -> Path:
    """Get default data directory (~/.wet-mcp/)."""
    return Path.home() / ".wet-mcp"


def _detect_gpu() -> bool:
    """Check if GPU is available via onnxruntime providers."""
    try:
        import onnxruntime as ort

        providers = ort.get_available_providers()
        return (
            "CUDAExecutionProvider" in providers or "DmlExecutionProvider" in providers
        )
    except Exception:
        return False


def _has_gguf_support() -> bool:
    """Check if llama-cpp-python is installed for GGUF models."""
    try:
        import llama_cpp  # noqa: F401

        return True
    except ImportError:
        return False


def _resolve_local_model(onnx_name: str, gguf_name: str) -> str:
    """Choose local model variant: GGUF if GPU + llama-cpp, else ONNX."""
    if _detect_gpu() and _has_gguf_support():
        return gguf_name
    return onnx_name


# Known providers that support reranking via LiteLLM
_RERANK_PROVIDERS: dict[str, str] = {
    "COHERE_API_KEY": "cohere/rerank-multilingual-v3.0",
}


class Settings(BaseSettings):
    """WET MCP Server configuration.

    Environment variables:
    - SEARXNG_URL: SearXNG instance URL (default: http://localhost:8080)
    - API_KEYS: Provider API keys, supports multiple providers
        Format: "ENV_VAR:key,ENV_VAR:key,..."
        Example: "GOOGLE_API_KEY:AIza...,COHERE_API_KEY:..."
        Embedding providers: Google, OpenAI, Cohere
        Reranking providers: Cohere (auto-detected)
    - EMBEDDING_MODEL: LiteLLM embedding model (auto-detected if not set)
    - EMBEDDING_DIMS: Embedding dimensions (0 = auto-detect, default 768)
    - EMBEDDING_BACKEND: "litellm" | "local" (auto: API_KEYS -> litellm, else local)
        Local: GGUF if GPU + llama-cpp-python, else ONNX
    - RERANK_ENABLED: Enable reranking (default: true)
    - RERANK_BACKEND: "litellm" | "local" (auto: Cohere key -> litellm, else local)
    - RERANK_MODEL: LiteLLM rerank model (auto-detected from API_KEYS if Cohere)
    - RERANK_TOP_N: Return top N results after reranking (default: 10)
    - SYNC_ENABLED: Enable rclone sync (default: false)
    - SYNC_REMOTE: Rclone remote name (e.g., "gdrive")
    - SYNC_FOLDER: Remote folder name (default: "wet-mcp")
    - SYNC_INTERVAL: Auto-sync interval in seconds (0 = manual only)
    """

    # SearXNG
    searxng_url: str = "http://localhost:41592"
    searxng_timeout: int = 30

    # Crawler
    crawler_headless: bool = True
    crawler_timeout: int = 60

    # SearXNG Management
    wet_auto_searxng: bool = True
    wet_searxng_port: int = 41592

    # Tool execution timeout (seconds, 0 = no timeout)
    tool_timeout: int = 120

    # Media
    download_dir: str = "~/.wet-mcp/downloads"

    # Media Analysis (LiteLLM)
    api_keys: str | None = None  # ENV_VAR:key,ENV_VAR:key (multiple providers)
    llm_models: str = "gemini/gemini-3-flash-preview"  # provider/model (fallback chain)
    llm_temperature: float | None = None

    # Cache (web operations)
    wet_cache: bool = True  # Enable/disable web cache
    cache_dir: str = ""  # Cache database directory, default: ~/.wet-mcp

    # Docs storage
    docs_db_path: str = ""  # Default: ~/.wet-mcp/docs.db

    # Embedding
    embedding_model: str = ""  # LiteLLM format, auto-detect if empty
    embedding_dims: int = 0  # 0 = use server default (768)
    embedding_backend: str = (
        ""  # "litellm" | "local" | "" (auto: API_KEYS->litellm, else local)
    )

    # Reranking
    rerank_enabled: bool = (
        True  # Enable reranking (always available via local fallback)
    )
    rerank_backend: str = (
        ""  # "litellm" | "local" | "" (auto: Cohere->litellm, else local)
    )
    rerank_model: str = (
        ""  # LiteLLM rerank model (e.g., "cohere/rerank-multilingual-v3.0")
    )
    rerank_top_n: int = 10  # Return top N after reranking

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
        """Return explicit EMBEDDING_MODEL or None for auto-detect."""
        if self.embedding_model:
            return self.embedding_model
        return None

    def resolve_embedding_dims(self) -> int:
        """Return explicit EMBEDDING_DIMS or 0 for auto-detect."""
        return self.embedding_dims

    def resolve_local_embedding_model(self) -> str:
        """Resolve local embedding model: GGUF if GPU + llama-cpp, else ONNX."""
        return _resolve_local_model(
            "n24q02m/Qwen3-Embedding-0.6B-ONNX",
            "n24q02m/Qwen3-Embedding-0.6B-GGUF",
        )

    def resolve_embedding_backend(self) -> str:
        """Resolve embedding backend: 'local' or 'litellm'.

        Always returns a valid backend (never empty).

        Auto-detect order:
        1. Explicit EMBEDDING_BACKEND setting
        2. 'litellm' if API keys are configured
        3. 'local' (qwen3-embed built-in, always available)
        """
        if self.embedding_backend:
            return self.embedding_backend
        if self.api_keys:
            return "litellm"
        return "local"

    # --- Reranking resolution ---

    def resolve_local_rerank_model(self) -> str:
        """Resolve local rerank model: GGUF if GPU + llama-cpp, else ONNX."""
        return _resolve_local_model(
            "n24q02m/Qwen3-Reranker-0.6B-ONNX",
            "n24q02m/Qwen3-Reranker-0.6B-GGUF",
        )

    def resolve_rerank_backend(self) -> str:
        """Resolve reranking backend: 'local', 'litellm', or ''.

        Returns '' only if reranking is explicitly disabled.
        Always returns a valid backend otherwise.

        Auto-detect order:
        1. Explicit RERANK_BACKEND setting
        2. 'litellm' if RERANK_MODEL is set
        3. 'litellm' if API_KEYS contains a rerank-capable provider (Cohere)
        4. 'local' (qwen3-embed built-in, always available)
        """
        if not self.rerank_enabled:
            return ""
        if self.rerank_backend:
            return self.rerank_backend
        if self.rerank_model:
            return "litellm"
        if self.api_keys:
            for provider_key in _RERANK_PROVIDERS:
                if provider_key in self.api_keys:
                    return "litellm"
        return "local"

    def resolve_rerank_model(self) -> str | None:
        """Resolve rerank model from config or auto-detect from API_KEYS."""
        if self.rerank_model:
            return self.rerank_model
        if self.api_keys:
            for provider_key, model in _RERANK_PROVIDERS.items():
                if provider_key in self.api_keys:
                    return model
        return None


settings = Settings()
