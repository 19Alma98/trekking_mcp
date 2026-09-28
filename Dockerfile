# syntax=docker/dockerfile:1

FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim AS builder

WORKDIR /app

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

COPY pyproject.toml uv.lock README.md LICENSE ./
COPY src ./src

RUN uv sync --frozen --no-dev --no-editable

FROM python:3.13-slim-bookworm

WORKDIR /app

RUN useradd --create-home --uid 1000 --user-group trekking

COPY --from=builder --chown=trekking:trekking /app /app

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1

USER trekking

EXPOSE 8000

# Liveness: non controlla Overpass/Nominatim
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2)"

# Bind pubblico richiede --allow-host (vedi DEVELOPMENT §3.18).
# Per un hostname pubblico: docker run ... trekking-mcp --transport http \
#   --host 0.0.0.0 --port 8000 --allow-host 'tuo.dominio:*'
CMD ["trekking-mcp", "--transport", "http", "--host", "0.0.0.0", "--port", "8000", \
     "--allow-host", "127.0.0.1:*", "--allow-host", "localhost:*"]
