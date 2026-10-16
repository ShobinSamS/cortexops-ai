FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.7.12 /uv /usr/local/bin/uv
WORKDIR /app
ENV PYTHONUNBUFFERED=1 UV_LINK_MODE=copy UV_COMPILE_BYTECODE=1 UV_CACHE_DIR=/tmp/uv-cache CORTEXOPS_ROOT=/app HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project && useradd --uid 10001 --create-home cortexops && mkdir -p /data/uploads && chown -R cortexops:cortexops /data
COPY app ./app
COPY alembic ./alembic
COPY alembic.ini ./
USER cortexops
EXPOSE 8000
CMD ["uv", "run", "--no-sync", "python", "-m", "app"]
