"""Configuration settings for WET MCP Server."""

import importlib.util
import os
from pathlib import Path

from loguru import logger
from mcp_core.llm.providers import key_env_for_model
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


class Settings(BaseSettings):
    """WET MCP Server configuration.

    Environment variables:
    - SEARXNG_URL: SearXNG instance URL (default: http://localhost:8080)
    - API_KEYS: Provider API keys, supports multiple providers
        Format: "ENV_VAR:key,ENV_VAR:key,..."
        Or file path: "@path/to/keys"
        Example: "GOOGLE_API_KEY:AIza...,COHERE_API_KEY:..."
        Embedding providers: Jina, Google, OpenAI, Cohere
        Reranking providers: Jina, Cohere
    - EMBEDDING_MODELS: Embedding model chain "provider/model,..." (order =
        litellm fallback). Empty -> curated default filtered to configured
        keys; no usable key -> local ONNX. Backend inferred from this chain.
    - RERANK_MODELS: Rerank model chain (same semantics as EMBEDDING_MODELS).
    - EMBEDDING_DIMS: Embedding dimensions (0 = auto-detect, default 768)
    - RERANK_ENABLED: Enable reranking (default: true)
    - RERANK_TOP_N: Return top N results after reranking (default: 10)
    - EMBEDDING_MODEL / EMBEDDING_BACKEND / RERANK_MODEL / RERANK_BACKEND:
        DEPRECATED (2026-06-11) -- singular model + backend env vars, folded
        into the plural *_MODELS chain (honored one release with a warning).
        Local: GGUF if GPU + llama-cpp-python, else ONNX.
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
    # web-core runner tries Docker fallback first, then subprocess install.
    # On Windows, Docker path handles lxml/build-tool constraints that would
    # otherwise block the subprocess path -- so auto-start works cross-platform
    # as long as Docker Desktop OR build tools are available.
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

    # Per-task model chains "provider/model,provider/model" (order = litellm
    # fallback). Empty -> local ONNX. Replaces the priority-router auto-detect
    # and the singular EMBEDDING_MODEL/EMBEDDING_BACKEND (deprecated shims).
    embedding_models: str = ""
    rerank_models: str = ""
    # DEPRECATED (2026-06-11): folded into EMBEDDING_MODELS/RERANK_MODELS,
    # honored one release with a warning. Backend now inferred.

    # Embedding
    embedding_model: str = ""  # DEPRECATED: folded into EMBEDDING_MODELS
    embedding_dims: int = 0  # 0 = use server default (768)
    embedding_backend: str = ""  # DEPRECATED: inferred from EMBEDDING_MODELS

    # B2: docs vector-store embedding-model identity guard. When the active
    # embedding model/dims differ from what the store was built with, DocsDB
    # raises EmbeddingModelMismatch by default (safe). Set this to rebuild:
    # the vector table is dropped + re-stamped and the docs-embed pipeline
    # repopulates it on the next pass.
    reindex_on_model_change: bool = False  # env REINDEX_ON_MODEL_CHANGE

    # BYO local model override. When set, the LOCAL embedding/rerank backend
    # loads this model id instead of the bundled Qwen3 default. A non-built-in
    # id is registered with qwen3-embed at startup using the companion vars
    # below (embedding only; rerank custom registration is a follow-up).
    local_embedding_model: str = ""  # env LOCAL_EMBEDDING_MODEL
    local_rerank_model: str = ""  # env LOCAL_RERANK_MODEL
    # Companion vars for registering a custom LOCAL embedding model (BYO ONNX).
    # Required only when LOCAL_EMBEDDING_MODEL is a non-built-in id.
    local_embedding_pooling: str = "MEAN"  # MEAN | CLS | LAST_TOKEN | DISABLED
    local_embedding_dim: int = 0  # required (>0) for a custom embedding model
    local_embedding_normalize: bool = True
    local_embedding_model_file: str = "onnx/model.onnx"

    # Reranking
    rerank_enabled: bool = (
        True  # Enable reranking (always available via local fallback)
    )
    rerank_backend: str = ""  # DEPRECATED: inferred from RERANK_MODELS
    rerank_model: str = ""  # DEPRECATED: folded into RERANK_MODELS
    rerank_top_n: int = 10  # Return top N after reranking

    # Docs sync (Google Drive API)
    sync_enabled: bool = True
    sync_folder: str = "wet-mcp"  # Google Drive folder name
    sync_interval: int = 300  # seconds, 0 = manual only
    google_drive_client_id: str = (
        "147668446467-olf2cf6e49rshqv9quvhq639110oc6hc.apps.googleusercontent.com"
    )
    google_drive_client_secret: str = "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"

    # S3-compatible sync (operator deploy mode).
    # When SYNC_S3_BUCKET is non-empty the active backend resolves to "s3"
    # and the Google Drive OAuth flow is DISABLED. Used in HTTP / Docker
    # deploy mode where the operator pre-provisions a bucket for docs.db
    # backup/restore instead of relying on per-user GDrive OAuth.
    # Mutually exclusive with the GDrive flow at deployment level - the
    # two backends MUST NOT both be active in the same process.
    sync_s3_bucket: str = ""
    sync_s3_region: str = "us-east-1"
    sync_s3_endpoint: str = ""  # custom endpoint for R2 / B2 / MinIO
    sync_s3_access_key_id: str = ""
    sync_s3_secret_access_key: str = ""
    sync_s3_prefix: str = "docs/"

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

    # --- Per-task model chains ---

    # Explicit provider prefixes so key-availability filtering + litellm
    # routing are unambiguous (cohere/openai bare names would mis-detect).
    _DEFAULT_EMBEDDING_CHAIN = (
        "jina_ai/jina-embeddings-v5-text-small",
        "gemini/gemini-embedding-001",
        "openai/text-embedding-3-large",
        "cohere/embed-multilingual-v3.0",
    )
    _DEFAULT_RERANK_CHAIN = (
        "jina_ai/jina-reranker-v3",
        "cohere/rerank-v3.5",
    )

    def _key_available(self, env_var: str) -> bool:
        """Whether a provider key is set (env or GOOGLE->GEMINI alias)."""
        if os.getenv(env_var):
            return True
        # GOOGLE_API_KEY satisfies GEMINI_API_KEY (wet's _ENV_ALIASES)
        aliases = getattr(self, "_ENV_ALIASES", {})
        for alias, canonical in aliases.items():
            if canonical == env_var and os.getenv(alias):
                return True
        return False

    def _chain(self, primary: str, legacy: str, default: tuple[str, ...]) -> list[str]:
        if primary:
            return [m.strip() for m in primary.split(",") if m.strip()]
        if legacy:
            logger.warning(
                "Deprecated singular model env honored; migrate to the plural "
                "<TASK>_MODELS chain (removed next release): {!r}",
                legacy,
            )
            return [legacy.strip()]
        # Curated default, but ONLY models whose provider key is configured;
        # none -> empty -> local ONNX (no priority-router, no keyless cloud).
        return [m for m in default if self._key_available(key_env_for_model(m))]

    def embedding_chain(self) -> list[str]:
        return self._chain(
            self.embedding_models, self.embedding_model, self._DEFAULT_EMBEDDING_CHAIN
        )

    def rerank_chain(self) -> list[str]:
        if not self.rerank_enabled:
            return []
        return self._chain(
            self.rerank_models, self.rerank_model, self._DEFAULT_RERANK_CHAIN
        )

    def embedding_primary(self) -> str | None:
        c = self.embedding_chain()
        return c[0] if c else None

    def rerank_primary(self) -> str | None:
        c = self.rerank_chain()
        return c[0] if c else None

    def llm_chain(self) -> list[str]:
        return [m.strip() for m in self.llm_models.split(",") if m.strip()]

    # --- Embedding resolution ---

    def resolve_embedding_dims(self) -> int:
        """Return explicit EMBEDDING_DIMS or 0 for auto-detect."""
        return self.embedding_dims

    def resolve_local_embedding_model(self) -> str:
        """Resolve local embedding model: GGUF if GPU + llama-cpp, else ONNX.

        LOCAL_EMBEDDING_MODEL overrides the bundled default (BYO model).
        """
        if self.local_embedding_model:
            return self.local_embedding_model
        return _resolve_local_model(
            "n24q02m/Qwen3-Embedding-0.6B-ONNX",
            "n24q02m/Qwen3-Embedding-0.6B-GGUF",
        )

    def resolve_embedding_backend(self) -> str:
        """Resolve embedding backend: 'local' or 'cloud'.

        Always returns a valid backend (never empty). Backend is inferred
        from EMBEDDING_MODELS (non-empty chain -> cloud, empty -> local);
        the deprecated EMBEDDING_BACKEND env var is honored for one release.
        """
        if self.embedding_backend:
            logger.warning(
                "Deprecated EMBEDDING_BACKEND honored; inferred from "
                "EMBEDDING_MODELS now."
            )
            return (
                "cloud"
                if self.embedding_backend in ("cloud", "litellm")
                else self.embedding_backend
            )
        return "cloud" if self.embedding_chain() else "local"

    # --- Reranking resolution ---

    def resolve_local_rerank_model(self) -> str:
        """Resolve local rerank model: GGUF if GPU + llama-cpp, else ONNX.

        The ONNX default is the YesNo variant (~598 MB at inference vs ~12 GB
        for the full-vocab build); it is mathematically equivalent and, since
        qwen3-embed 1.11.2b3, produces batch-invariant scores (issue #725).

        LOCAL_RERANK_MODEL overrides the bundled default (BYO model).
        """
        if self.local_rerank_model:
            return self.local_rerank_model
        return _resolve_local_model(
            "n24q02m/Qwen3-Reranker-0.6B-ONNX-YesNo",
            "n24q02m/Qwen3-Reranker-0.6B-GGUF",
        )

    def resolve_rerank_backend(self) -> str:
        """Resolve reranking backend: 'cloud', 'local', or '' (disabled).

        Disabled when rerank_enabled is False. Otherwise inferred from
        RERANK_MODELS (non-empty chain -> cloud, empty -> local); the
        deprecated RERANK_BACKEND env var is honored for one release.
        """
        if not self.rerank_enabled:
            return ""
        if self.rerank_backend:
            logger.warning(
                "Deprecated RERANK_BACKEND honored; inferred from RERANK_MODELS now."
            )
            return (
                "cloud"
                if self.rerank_backend in ("cloud", "litellm")
                else self.rerank_backend
            )
        return "cloud" if self.rerank_chain() else "local"

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
            logger.info("SDK direct mode (litellm passthrough via mcp_core.llm)")
        else:
            logger.info("Local mode (no cloud providers)")

        return mode


settings = Settings()
