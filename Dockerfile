# Multi-stage build for wet-mcp
# Python 3.13 + SearXNG + Playwright chromium
# All-in-one: no external Docker or services needed

FROM python:3.13-slim-bookworm AS builder

WORKDIR /app

# Install git (required by SearXNG build system for version detection)
RUN apt-get update && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

# Copy project files
COPY pyproject.toml uv.lock README.md ./
COPY src/ ./src/

# Install dependencies
RUN uv sync --frozen --no-dev

# Install SearXNG from GitHub (zip archive + no-build-isolation for speed)
# Then patch version_frozen.py (zip has no .git for version detection)
RUN uv pip install --quiet msgspec setuptools wheel pyyaml \
    && uv pip install --quiet --no-build-isolation \
    https://github.com/searxng/searxng/archive/refs/heads/master.zip \
    && uv run python -c "\
import importlib.util; from pathlib import Path; \
spec = importlib.util.find_spec('searx'); \
vf = Path(spec.submodule_search_locations[0]) / 'version_frozen.py'; \
vf.write_text('VERSION_STRING = \"0.0.0\"\nVERSION_TAG = \"v0.0.0\"\nDOCKER_TAG = \"\"\nGIT_URL = \"https://github.com/searxng/searxng\"\nGIT_BRANCH = \"master\"\n'); \
print(f'Created {vf}')"

# Install Playwright chromium browser
RUN uv run python -m playwright install chromium

FROM python:3.13-slim-bookworm

# Create non-root user
RUN useradd -m -u 1000 app

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
    # SearXNG dependencies
    libxml2 \
    libxslt1.1 \
    # General
    fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

# Copy virtual environment from builder
COPY --from=builder --chown=app:app /app/.venv /app/.venv
COPY --from=builder --chown=app:app /app/src /app/src

# Copy Playwright browsers from builder
COPY --from=builder --chown=app:app /root/.cache/ms-playwright /home/app/.cache/ms-playwright

# Activate venv
ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONPATH=/app/src

# Mark setup as complete (everything pre-installed)
RUN mkdir -p /home/app/.wet-mcp \
    && touch /home/app/.wet-mcp/.setup-complete \
    && chown -R app:app /home/app/.wet-mcp

# Switch to non-root user
USER app

# Stdio transport by default
CMD ["python", "-m", "wet_mcp"]
