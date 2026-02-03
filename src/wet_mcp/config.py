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

    # Logging
    log_level: str = "INFO"

    model_config = {"env_prefix": "", "case_sensitive": False}


settings = Settings()
