FROM python:3.14.6-slim-bookworm AS builder

COPY --from=ghcr.io/astral-sh/uv:0.11.25 /uv /uvx /bin/
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv

WORKDIR /app

# Install dependencies first (better layer caching) - no project sources yet
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-install-project --no-dev

COPY pyproject.toml uv.lock ./
COPY src ./src

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev


FROM python:3.14.6-slim-bookworm AS runtime

RUN groupadd --system --gid 1001 app \
 && useradd  --system --uid 1001 --gid app --home /app --shell /sbin/nologin app

WORKDIR /app

COPY --from=builder --chown=app:app /app/.venv /app/.venv
COPY --from=builder --chown=app:app /app/src  /app/src

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONPATH="/app/src" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

USER app

CMD ["python", "-m", "app"]