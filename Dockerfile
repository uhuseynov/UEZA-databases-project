
# =============================================================================
# Builder
# =============================================================================

FROM python:3.14-slim AS builder

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv

WORKDIR /app

# Build dependencies for native Python extensions (mwparserfromhell).
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        gcc \
        libc6-dev \
    && rm -rf /var/lib/apt/lists/*

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
    PYTHONPATH=/app \
    PATH="/app/.venv/bin:$PATH" \
    HF_HOME=/app/.cache/huggingface

WORKDIR /app

# The application runs as this user (scripts/entrypoint.sh drops root before it starts).
# Only /app/.cache, where the article cache and the model cache live, is writable by it;
# the code and the virtual environment stay owned by root and read-only to the application.
RUN groupadd --system --gid 10001 ueza \
    && useradd --system --uid 10001 --gid ueza --no-create-home --shell /usr/sbin/nologin ueza \
    && mkdir -p /app/.cache \
    && chown ueza:ueza /app/.cache

COPY --from=builder /app/.venv /app/.venv

COPY src ./src
COPY data ./data
COPY scripts/entrypoint.sh ./scripts/entrypoint.sh

RUN chmod +x ./scripts/entrypoint.sh

EXPOSE 8000

ENTRYPOINT ["./scripts/entrypoint.sh"]

CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
