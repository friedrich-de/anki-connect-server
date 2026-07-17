FROM python:3.12-slim

WORKDIR /app

COPY --from=ghcr.io/astral-sh/uv:0.11.28 /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PATH="/app/.venv/bin:$PATH"

COPY pyproject.toml uv.lock README.md ./
RUN uv sync --locked --no-dev --no-install-project

COPY src ./src
RUN uv sync --locked --no-dev

RUN mkdir -p /data

ENV ANKICONNECT_COLLECTION_PATH=/data/collection.anki2 \
    ANKICONNECT_PORT=8765 \
    ANKICONNECT_BIND=0.0.0.0

EXPOSE 8765

CMD ["anki-connect-server", "api"]
