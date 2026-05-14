# Playwright's official Python image: Ubuntu 22.04 + Python 3.11 + Chromium + deps.
# Using a pinned tag keeps builds reproducible.
FROM mcr.microsoft.com/playwright/python:v1.48.0-jammy

# uv handles deps via pyproject.toml + uv.lock.
RUN pip install --no-cache-dir uv==0.5.4

WORKDIR /app

# Copy dependency manifests first so Docker can cache the install layer
# until pyproject.toml or uv.lock actually change.
COPY pyproject.toml uv.lock ./

# Install runtime deps only (skip ruff/pyright/pytest-playwright dev group).
RUN uv sync --frozen --no-dev --no-install-project

# Copy application code.
COPY app ./app
COPY scripts ./scripts
COPY templates ./templates
COPY static ./static

# Install the project itself into the venv.
RUN uv sync --frozen --no-dev

# Settings.data_dir defaults to "data"; we bind-mount /app/data from the host
# so credentials.enc, moso-headers.json, sessions, and reports survive
# container restarts.
RUN mkdir -p /app/data

EXPOSE 8080

# Healthcheck — uvicorn responding on /
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://localhost:8080/ -o /dev/null || exit 1

# Run the FastAPI app via uv (uses the project's venv).
CMD ["uv", "run", "--no-dev", "uvicorn", \
     "--factory", "app.main:create_app", \
     "--host", "0.0.0.0", "--port", "8080"]
