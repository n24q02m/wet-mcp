"""Docker container management for SearXNG."""

import socket
from importlib.resources import files
from pathlib import Path

from loguru import logger

from wet_mcp.config import settings


def _find_available_port(start_port: int, max_tries: int = 10) -> int:
    """Find an available port starting from start_port."""
    for offset in range(max_tries):
        port = start_port + offset
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(("localhost", port))
                return port
        except OSError:
            continue
    # Fallback to original port
    return start_port


def _get_settings_path() -> Path:
    """Get path to SearXNG settings file.

    Copies bundled settings.yml to user config directory for Docker mounting.
    Uses ~/.wet-mcp/ which is typically shared with Docker.
    """
    config_dir = Path.home() / ".wet-mcp"
    config_dir.mkdir(parents=True, exist_ok=True)

    settings_file = config_dir / "searxng_settings.yml"

    # Copy bundled settings if not exists
    if not settings_file.exists():
        bundled = files("wet_mcp").joinpath("searxng_settings.yml")
        settings_file.write_text(bundled.read_text())
        logger.debug(f"Copied SearXNG settings to: {settings_file}")

    return settings_file


def ensure_searxng() -> str:
    """Start SearXNG container if not running. Returns URL.

    This function handles:
    - Automatic container creation if it doesn't exist
    - Port conflict resolution (tries next available port)
    - SearXNG configuration for JSON API format via settings.yml mount
    - Graceful fallback to external SearXNG URL if Docker unavailable
    """
    if not settings.wet_auto_docker:
        logger.info("Auto Docker disabled, using external SearXNG")
        return settings.searxng_url

    try:
        from python_on_whales import DockerException, docker
    except ImportError:
        logger.warning("python-on-whales not installed, using external SearXNG")
        return settings.searxng_url

    container_name = settings.wet_container_name
    image = settings.wet_searxng_image
    preferred_port = settings.wet_searxng_port

    try:
        if docker.container.exists(container_name):
            container = docker.container.inspect(container_name)
            if container.state.running:
                logger.debug(f"SearXNG container already running: {container_name}")
                # Extract port from running container
                ports = container.network_settings.ports
                if ports and "8080/tcp" in ports and ports["8080/tcp"]:
                    port = int(ports["8080/tcp"][0].get("HostPort", preferred_port))
                else:
                    port = preferred_port
            else:
                logger.info(f"Starting stopped container: {container_name}")
                docker.container.start(container_name)
                port = preferred_port
        else:
            # Find available port to avoid conflicts
            port = _find_available_port(preferred_port)
            if port != preferred_port:
                logger.info(f"Port {preferred_port} in use, using {port}")

            # Get settings file path
            settings_path = _get_settings_path()

            logger.info(f"Starting SearXNG container: {container_name}")
            docker.run(
                image,
                name=container_name,
                detach=True,
                publish=[(port, 8080)],
                volumes=[(str(settings_path), "/etc/searxng/settings.yml", "ro")],
                envs={
                    "SEARXNG_SECRET": "wet-internal",
                },
            )
            logger.info(f"SearXNG container started on port {port}")

        return f"http://localhost:{port}"

    except DockerException as e:
        logger.warning(f"Docker not available: {e}")
        logger.warning("Falling back to external SearXNG URL")
        return settings.searxng_url
    except Exception as e:
        logger.error(f"Failed to start SearXNG: {e}")
        return settings.searxng_url


def stop_searxng() -> None:
    """Stop SearXNG container if running."""
    if not settings.wet_auto_docker:
        return

    try:
        from python_on_whales import docker

        container_name = settings.wet_container_name
        if docker.container.exists(container_name):
            logger.info(f"Stopping container: {container_name}")
            docker.container.stop(container_name)
    except Exception as e:
        logger.debug(f"Failed to stop container: {e}")


def remove_searxng() -> None:
    """Stop and remove SearXNG container."""
    if not settings.wet_auto_docker:
        return

    try:
        from python_on_whales import docker

        container_name = settings.wet_container_name
        if docker.container.exists(container_name):
            logger.info(f"Removing container: {container_name}")
            docker.container.remove(container_name, force=True)  # type: ignore
    except Exception as e:
        logger.debug(f"Failed to remove container: {e}")
