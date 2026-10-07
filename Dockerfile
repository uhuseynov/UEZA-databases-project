# =============================================================================
# Builder
# =============================================================================

FROM python:3.14-slim AS builder

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv

WORKDIR /app

RUN pip install --no-cache-dir uv

COPY pyproject.toml uv.lock ./

RUN uv sync \
    --frozen \
    --no-dev \
    --no-install-project


# =============================================================================
# Runtime
# =============================================================================

FROM python:3.14-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app/src \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

COPY --from=builder /app/.venv /app/.venv

COPY src ./src
COPY alembic.ini ./
COPY scripts/entrypoint.sh ./scripts/entrypoint.sh

RUN chmod +x ./scripts/entrypoint.sh

EXPOSE 8000

ENTRYPOINT ["./scripts/entrypoint.sh"]

CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]