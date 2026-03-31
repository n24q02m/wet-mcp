"""Configuration settings for WET MCP Server."""

import importlib.util
import os
from pathlib import Path

from loguru import logger
from pydantic import SecretStr
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
    return importlib.util.find_spec("llama_cpp") is not None


def _resolve_local_model(onnx_name: str, gguf_name: str) -> str:
    """Choose local model variant: GGUF if GPU + llama-cpp, else ONNX."""
    if _detect_gpu() and _has_gguf_support():
        return gguf_name
    return onnx_name


# Known providers that support reranking
_RERANK_PROVIDERS: dict[str, str] = {
    "JINA_AI_API_KEY": "jina_ai/jina-reranker-v3",
    "COHERE_API_KEY": "cohere/rerank-v4.0-pro",
}

# Known providers that support embedding
_EMBEDDING_PROVIDERS: dict[str, str] = {
    "JINA_AI_API_KEY": "jina_ai/jina-embeddings-v5-text-small",
    "GEMINI_API_KEY": "gemini/gemini-embedding-001",
    "GOOGLE_API_KEY": "gemini/gemini-embedding-001",
    "OPENAI_API_KEY": "text-embedding-3-large",
    "COHERE_API_KEY": "embed-multilingual-v3.0",
}


class Settings(BaseSettings):
    """WET MCP Server configuration.

    Environment variables:
    - SEARXNG_URL: SearXNG instance URL (default: http://localhost:8080)
    - API_KEYS: Provider API keys, supports multiple providers
        Format: "ENV_VAR:key,ENV_VAR:key,..."
        Or file path: "@path/to/keys"
        Example: "GOOGLE_API_KEY:AIza...,COHERE_API_KEY:..."
        Embedding providers: Jina, Google, OpenAI, Cohere
        Reranking providers: Jina, Cohere (auto-detected)
    - EMBEDDING_MODEL: Embedding model (auto-detected if not set)
    - EMBEDDING_DIMS: Embedding dimensions (0 = auto-detect, default 768)
    - EMBEDDING_BACKEND: "cloud" | "local" (auto: API_KEYS -> cloud, else local)
        Local: GGUF if GPU + llama-cpp-python, else ONNX
    - RERANK_ENABLED: Enable reranking (default: true)
    - RERANK_BACKEND: "cloud" | "local" (auto: Cohere key -> cloud, else local)
    - RERANK_MODEL: Rerank model (auto-detected from API_KEYS if Cohere)
    - RERANK_TOP_N: Return top N results after reranking (default: 10)
    - SYNC_ENABLED: Enable Google Drive sync (default: true)
    - SYNC_FOLDER: Google Drive folder name (default: "wet-mcp")
    - SYNC_INTERVAL: Auto-sync interval in seconds (default: 300)
    - GOOGLE_DRIVE_CLIENT_ID: OAuth client ID for Google Drive sync

    Provider Mode Detection (resolve_provider_mode):
    - "sdk": API_KEYS set -> direct SDK calls
    - "local": no keys -> local ONNX models only
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

    # Media Analysis (Provider API keys)
    api_keys: SecretStr | None = None  # ENV_VAR:key,ENV_VAR:key (multiple providers)

    llm_models: str = "gemini/gemini-3-flash-preview,openai/gpt-5.4-mini-2026-03-17"  # provider/model (fallback chain)
    llm_temperature: float | None = None

    # Cache (web operations)
    wet_cache: bool = True  # Enable/disable web cache
    cache_dir: str = ""  # Cache database directory, default: ~/.wet-mcp

    # Docs storage
    docs_db_path: str = ""  # Default: ~/.wet-mcp/docs.db

    # Embedding
    embedding_model: str = ""  # Model name, auto-detect if empty
    embedding_dims: int = 0  # 0 = use server default (768)
    embedding_backend: str = ""  # "cloud" | "local" | "" (auto)

    # Reranking
    rerank_enabled: bool = (
        True  # Enable reranking (always available via local fallback)
    )
    rerank_backend: str = ""  # "cloud" | "local" | "" (auto)
    rerank_model: str = ""  # Rerank model (e.g., "rerank-v4.0-pro")
    rerank_top_n: int = 10  # Return top N after reranking

    # Docs sync (Google Drive API)
    sync_enabled: bool = True
    sync_folder: str = "wet-mcp"  # Google Drive folder name
    sync_interval: int = 300  # seconds, 0 = manual only
    google_drive_client_id: str = (
        "147668446467-olf2cf6e49rshqv9quvhq639110oc6hc.apps.googleusercontent.com"
    )
    google_drive_client_secret: str = "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"

    # Logging
    log_level: str = "INFO"

    # Local file conversion
    convert_max_file_size: int = 104857600  # 100MB
    convert_allowed_dirs: str = ""  # comma-separated absolute paths, empty = allow all

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

    # Some providers use different env vars for embeddings vs completions
    _ENV_ALIASES: dict[str, str] = {
        "GOOGLE_API_KEY": "GEMINI_API_KEY",
    }

    def setup_api_keys(self) -> dict[str, list[str]]:
        """Parse API_KEYS and set env vars for provider SDKs.

        Format: "GOOGLE_API_KEY:AIza...,OPENAI_API_KEY:sk-..."
        Or file: "@path/to/keys_file"

        Also sets aliases (e.g., GOOGLE_API_KEY -> GEMINI_API_KEY)
        because Gemini SDK uses GEMINI_API_KEY.

        Returns:
            Dict mapping env var name to list of API keys.
        """
        if not self.api_keys:
            return {}

        keys_by_env: dict[str, list[str]] = {}
        api_keys_str = self.api_keys.get_secret_value()

        # Handle file-based keys
        if api_keys_str.startswith("@"):
            path_str = api_keys_str[1:]
            path = Path(path_str).expanduser()
            if not path.exists():
                raise FileNotFoundError(f"API keys file not found: {path}")

            try:
                # Read content and normalize newlines to commas
                content = path.read_text(encoding="utf-8").strip()
                api_keys_str = content.replace("\n", ",")
            except Exception as e:
                raise ValueError(f"Failed to read API keys file: {e}") from e

        for pair in api_keys_str.split(","):
            pair = pair.strip()
            if ":" not in pair:
                continue

            env_var, key = pair.split(":", 1)
            env_var = env_var.strip()
            key = key.strip()

            if not key:
                continue

            keys_by_env.setdefault(env_var, []).append(key)

        # Set first key of each env var (SDKs read from env)
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
        """Resolve embedding backend: 'local' or 'cloud'.

        Always returns a valid backend (never empty).

        Auto-detect order:
        1. Explicit EMBEDDING_BACKEND setting
        2. 'cloud' if API keys are configured
        3. 'local' (qwen3-embed built-in, always available)
        """
        if self.embedding_backend:
            return self.embedding_backend
        mode = self.resolve_provider_mode()
        if mode == "sdk":
            return "cloud"
        return "local"

    # --- Reranking resolution ---

    def resolve_local_rerank_model(self) -> str:
        """Resolve local rerank model: GGUF if GPU + llama-cpp, else ONNX."""
        return _resolve_local_model(
            "n24q02m/Qwen3-Reranker-0.6B-ONNX",
            "n24q02m/Qwen3-Reranker-0.6B-GGUF",
        )

    def resolve_rerank_backend(self) -> str:
        """Resolve reranking backend: 'local', 'cloud', or ''.

        Returns '' only if reranking is explicitly disabled.
        Always returns a valid backend otherwise.

        Auto-detect order:
        1. Explicit RERANK_BACKEND setting
        2. 'cloud' if RERANK_MODEL is set
        3. 'cloud' if API_KEYS contains a rerank-capable provider (Cohere)
        4. 'local' (qwen3-embed built-in, always available)
        """
        if not self.rerank_enabled:
            return ""
        if self.rerank_backend:
            return self.rerank_backend
        if self.rerank_model:
            return "cloud"

        # Check env vars first (populated by setup_api_keys)
        for provider_key in _RERANK_PROVIDERS:
            if os.environ.get(provider_key):
                return "cloud"

        if self.api_keys:
            val = self.api_keys.get_secret_value()
            if not val.startswith("@"):
                for provider_key in _RERANK_PROVIDERS:
                    if provider_key in val:
                        return "cloud"
        return "local"

    def resolve_rerank_model(self) -> str | None:
        """Resolve rerank model from config or auto-detect from API_KEYS."""
        if self.rerank_model:
            return self.rerank_model

        # Check env vars first
        for provider_key, model in _RERANK_PROVIDERS.items():
            if os.environ.get(provider_key):
                return model

        if self.api_keys:
            val = self.api_keys.get_secret_value()
            if not val.startswith("@"):
                for provider_key, model in _RERANK_PROVIDERS.items():
                    if provider_key in val:
                        return model
        return None

    # --- Provider mode resolution ---

    def resolve_provider_mode(self) -> str:
        """Detect provider mode: 'sdk' or 'local'.

        Returns 'sdk' if any API keys are configured, 'local' otherwise.
        """
        if self.api_keys:
            return "sdk"
        # Check for direct env var keys
        if any(
            os.getenv(k)
            for k in (
                "GEMINI_API_KEY",
                "GOOGLE_API_KEY",
                "OPENAI_API_KEY",
                "COHERE_API_KEY",
                "XAI_API_KEY",
                "JINA_AI_API_KEY",
            )
        ):
            return "sdk"
        return "local"

    def setup_providers(self) -> str:
        """One-time provider configuration. Call once during lifespan startup.

        Returns mode string: 'sdk' or 'local'.
        """
        mode = self.resolve_provider_mode()

        if mode == "sdk":
            self.setup_api_keys()
            logger.info("SDK direct mode (native provider SDKs)")
        else:
            logger.info("Local mode (no cloud providers)")

        return mode


# Embedding models to try during auto-detection (in priority order).
# Validated against API keys -- first success wins.
_EMBEDDING_CANDIDATES = [
    "jina_ai/jina-embeddings-v5-text-small",
    "gemini/gemini-embedding-001",
    "text-embedding-3-large",
    "embed-multilingual-v3.0",
]

settings = Settings()
