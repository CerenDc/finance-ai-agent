FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    UV_CACHE_DIR=/opt/uv-cache

WORKDIR /app

COPY requirements.txt requirements-mcp-server.txt ./

RUN python -m pip install --upgrade pip \
    && python -m pip install -r requirements.txt \
    && uv run --with "mcp[cli]==2.1.1" python -c "import mcp" \
    && useradd --create-home --uid 10001 appuser \
    && chown -R appuser:appuser /opt/uv-cache

COPY --chown=appuser:appuser app ./app
COPY --chown=appuser:appuser docker-entrypoint.sh ./docker-entrypoint.sh

USER appuser

EXPOSE 8000

CMD ["sh", "/app/docker-entrypoint.sh"]
