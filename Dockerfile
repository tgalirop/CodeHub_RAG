FROM ghcr.io/astral-sh/uv:0.12.23 AS uv
FROM python:3.12-slim
COPY --from=uv /uv /usr/local/bin/uv
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy PYTHONUNBUFFERED=1
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
COPY db ./db
COPY cloud ./cloud
COPY web/public ./web/public
RUN uv sync --locked --no-dev --no-editable && \
    useradd --create-home --uid 10001 app
ENV PATH="/app/.venv/bin:$PATH" RAG_MODEL_ROOT=/app/data/models \
    RAG_ARTIFACT_ROOT=/app/data/indexes RAG_WEB_ROOT=/app/web/public \
    HF_HUB_OFFLINE=1
USER app
EXPOSE 8000
CMD ["sh", "-c", "uvicorn codehub_rag.api:app --host 0.0.0.0 --port ${PORT:-8000}"]
