# One image for both services; APP_FACTORY selects which app runs.
#   API:    APP_FACTORY=bool_api.main:create_app   (default)
#   Worker: APP_FACTORY=bool_api.worker:create_app
FROM ghcr.io/astral-sh/uv:0.13.7 AS uv

FROM python:3.13-slim AS build
COPY --from=uv /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project
COPY src ./src
RUN uv sync --locked --no-dev --no-editable

FROM python:3.13-slim
RUN useradd --system --uid 10001 app
WORKDIR /app
COPY --from=build /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    APP_FACTORY=bool_api.main:create_app
USER app
CMD ["sh", "-c", "exec uvicorn --factory \"$APP_FACTORY\" --host 0.0.0.0 --port \"${PORT:-8080}\" --proxy-headers --forwarded-allow-ips='*'"]
