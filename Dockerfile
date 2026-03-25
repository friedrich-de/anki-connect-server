FROM python:3.12-slim

WORKDIR /app

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Copy pyproject.toml first for dependency caching
COPY pyproject.toml ./

# Install dependencies
RUN uv sync --frozen --no-install-project --no-dev

# Copy source code
COPY src/ ./src/
COPY tests/ ./tests/
COPY README.md ./
COPY AGENTS.md ./
COPY .env.example ./

# Create non-root user
RUN useradd --create-home appuser
USER appuser

# Environment variables
ENV ANKICONNECT_COLLECTION_PATH=/data/collection.anki21
ENV ANKICONNECT_PORT=8765
ENV ANKICONNECT_BIND=0.0.0.0

# Expose port
EXPOSE 8765

# Run the server
CMD ["uv", "run", "server"]
