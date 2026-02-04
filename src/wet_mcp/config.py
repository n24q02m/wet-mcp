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
        """Parse API_KEYS (format: ENV_VAR:key,...) and set env vars.

        Example:
            API_KEYS="GOOGLE_API_KEY:abc,GOOGLE_API_KEY:def,OPENAI_API_KEY:xyz"

        Returns:
            Dict mapping env var name to list of API keys.
        """
        if not self.api_keys:
            return {}

        import os

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

        return keys_by_env

    # Logging
    log_level: str = "INFO"

    model_config = {"env_prefix": "", "case_sensitive": False}


settings = Settings()
