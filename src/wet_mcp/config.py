"""Configuration settings for WET MCP Server."""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """WET MCP Server configuration."""

    # SearXNG
    searxng_url: str = "http://localhost:8080"
    searxng_timeout: int = 30

    # Crawler
    crawler_headless: bool = True
    crawler_timeout: int = 60

    # Docker Management
    wet_auto_docker: bool = True
    wet_container_name: str = "wet-searxng"
    wet_searxng_image: str = "searxng/searxng:latest"
    wet_searxng_port: int = 8080

    # Media
    download_dir: str = "~/.wet-mcp/downloads"

    # Media Analysis (LiteLLM)
    api_keys: str | None = None  # provider:key,provider:key
    llm_models: str = "gemini/gemini-3-flash-preview"  # provider/model (fallback chain)

    def setup_api_keys(self) -> dict[str, list[str]]:
        """Parse API_KEYS and set environment variables for LiteLLM."""
        if not self.api_keys:
            return {}

        import os

        env_map = {
            "gemini": "GOOGLE_API_KEY",
            "openai": "OPENAI_API_KEY",
            "anthropic": "ANTHROPIC_API_KEY",
            "groq": "GROQ_API_KEY",
            "deepseek": "DEEPSEEK_API_KEY",
            "mistral": "MISTRAL_API_KEY",
        }

        keys_by_provider: dict[str, list[str]] = {}

        for pair in self.api_keys.split(","):
            pair = pair.strip()
            if ":" not in pair:
                continue

            provider, key = pair.split(":", 1)
            provider = provider.strip().lower()
            key = key.strip()

            if not key:
                continue

            keys_by_provider.setdefault(provider, []).append(key)

        # Set first key of each provider as env var
        for provider, keys in keys_by_provider.items():
            if provider in env_map and keys:
                os.environ[env_map[provider]] = keys[0]

        return keys_by_provider

    # Logging
    log_level: str = "INFO"

    model_config = {"env_prefix": "", "case_sensitive": False}


settings = Settings()
