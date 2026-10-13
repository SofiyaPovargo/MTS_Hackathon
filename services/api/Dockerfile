# syntax=docker/dockerfile:1
# One image, three targets. The API target stays light; ML-heavy dependencies
# are added only to the worker target via the optional `ml` group.
FROM ghcr.io/astral-sh/uv:0.13.0-python3.13-trixie-slim AS base

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1

COPY pyproject.toml uv.lock README.md alembic.ini ./
RUN uv sync --frozen --no-dev --no-install-project

COPY src ./src
RUN uv sync --frozen --no-dev

# The image venv is already correct (runtime deps only, no dev group): prevent
# `uv run ...` from re-syncing and pulling dev dependencies at container start.
ENV UV_NO_SYNC=1

FROM base AS api
EXPOSE 8000
CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

FROM base AS worker
RUN uv sync --frozen --no-dev --extra ml
CMD ["uv", "run", "celery", "-A", "app.worker", "worker", "-l", "info"]