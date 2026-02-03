"""Auto-setup utilities for WET MCP Server.

This module handles automatic first-run setup:
- Install Playwright browsers (chromium)
- Verify Docker availability
- Create configuration directories

Setup runs automatically on first server start.
"""

import subprocess
import sys
from pathlib import Path

from loguru import logger

# Marker file to track if setup has been run
SETUP_MARKER = Path.home() / ".wet-mcp" / ".setup-complete"


def needs_setup() -> bool:
    """Check if setup needs to run."""
    return not SETUP_MARKER.exists()


def run_auto_setup() -> bool:
    """Run automatic setup on first start.

    Returns:
        True if setup succeeded or was already done, False on failure.
    """
    if not needs_setup():
        logger.debug("Setup already complete, skipping")
        return True

    logger.info("First run detected, running auto-setup...")

    success = True

    # Step 1: Create config directory
    config_dir = Path.home() / ".wet-mcp"
    config_dir.mkdir(parents=True, exist_ok=True)
    logger.debug(f"Created config directory: {config_dir}")

    # Step 2: Install Playwright chromium (required for Crawl4AI)
    logger.info("Installing Playwright chromium browser...")
    try:
        result = subprocess.run(
            [sys.executable, "-m", "playwright", "install", "chromium"],
            capture_output=True,
            text=True,
            timeout=300,
        )
        if result.returncode == 0:
            logger.info("Playwright chromium installed successfully")
        else:
            logger.warning(f"Playwright install warning: {result.stderr[:200]}")
            # Don't fail - might already be installed
    except subprocess.TimeoutExpired:
        logger.error("Playwright installation timed out")
        success = False
    except FileNotFoundError:
        logger.warning("Playwright command not found, some features may not work")

    # Step 3: Verify Docker (optional, for SearXNG)
    try:
        result = subprocess.run(
            ["docker", "version", "--format", "{{.Server.Version}}"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            logger.debug(f"Docker available: v{result.stdout.strip()}")
        else:
            logger.info("Docker not running, will use external SearXNG URL if configured")
    except FileNotFoundError:
        logger.info("Docker not installed, will use external SearXNG URL if configured")
    except subprocess.TimeoutExpired:
        logger.debug("Docker check timed out")

    # Mark setup as complete
    if success:
        SETUP_MARKER.touch()
        logger.info("Auto-setup complete!")

    return success


def reset_setup() -> None:
    """Reset setup marker to force re-run on next start."""
    if SETUP_MARKER.exists():
        SETUP_MARKER.unlink()
        logger.info("Setup marker removed, will re-run on next start")
