# syntax=docker/dockerfile:1
# Multi-stage build for wet-mcp
# Python 3.13 + SearXNG + Playwright chromium
# All-in-one: no external Docker or services needed

# ========================
# Stage 1: Builder
# ========================
FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim AS builder

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=0

WORKDIR /app

# Install git (required by SearXNG build system for version detection)
RUN apt-get update && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

# Install dependencies first (cached when deps don't change)
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --frozen --no-install-project --no-dev

# Copy application code and install the project
COPY . /app
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

# Install SearXNG from GitHub (zip archive + no-build-isolation for speed)
# Then patch version_frozen.py (zip has no .git for version detection)
RUN --mount=type=cache,target=/root/.cache/uv \
    uv pip install --quiet msgspec setuptools wheel pyyaml \
    && uv pip install --quiet --no-build-isolation \
    https://github.com/searxng/searxng/archive/refs/heads/master.zip \
    && uv run python -c "\
import importlib.util; from pathlib import Path; \
spec = importlib.util.find_spec('searx'); \
vf = Path(spec.submodule_search_locations[0]) / 'version_frozen.py'; \
vf.write_text('VERSION_STRING = \"0.0.0\"\nVERSION_TAG = \"v0.0.0\"\nDOCKER_TAG = \"\"\nGIT_URL = \"https://github.com/searxng/searxng\"\nGIT_BRANCH = \"master\"\n'); \
print(f'Created {vf}')"

# Install Playwright chromium browser
ENV PLAYWRIGHT_BROWSERS_PATH=/opt/playwright
RUN uv run python -m playwright install chromium

# ========================
# Stage 2: Runtime
# ========================
FROM python:3.13-slim-bookworm

WORKDIR /app

# Install Playwright runtime dependencies (system libs for chromium)
RUN apt-get update && apt-get install -y --no-install-recommends \
    # Playwright chromium dependencies
    libnss3 \
    libnspr4 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libdbus-1-3 \
    libxkbcommon0 \
    libatspi2.0-0 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libpango-1.0-0 \
    libcairo2 \
    libasound2 \
    libwayland-client0 \
    # D-Bus daemon (required by Chromium headless)
    dbus \
    # Additional Chromium dependencies
    libxshmfence1 \
    libx11-xcb1 \
    # SearXNG dependencies
    libxml2 \
    libxslt1.1 \
    # General
    fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

# Copy virtual environment and Playwright browsers from builder
COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /app/src /app/src
COPY --from=builder /opt/playwright /opt/playwright

# Set environment variables
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONPATH=/app/src \
    PLAYWRIGHT_BROWSERS_PATH=/opt/playwright \
    CACHE_DIR=/data \
    DOWNLOAD_DIR=/data/downloads \
    DBUS_SESSION_BUS_ADDRESS=disabled:

# Create non-root user and set permissions
RUN groupadd -r appuser && useradd -r -g appuser -d /home/appuser -m appuser \
    && mkdir -p /data/downloads /home/appuser/.wet-mcp \
    && touch /home/appuser/.wet-mcp/.setup-complete \
    && chown -R appuser:appuser /app /data /home/appuser /opt/playwright

VOLUME /data
USER appuser

# Stdio transport by default
CMD ["python", "-m", "wet_mcp"]
