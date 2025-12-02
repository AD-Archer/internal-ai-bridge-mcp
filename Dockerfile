FROM python:3.11-slim

# Prevent Python from writing .pyc files and buffer logs
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    ENV_FILE=/app/.env \
    PORT=8765 \
    CONVERSATION_DB_PATH=/app/data/conversation_history.db

WORKDIR /app

# Install runtime deps
RUN apt-get update && \
    apt-get install --no-install-recommends -y ca-certificates && \
    rm -rf /var/lib/apt/lists/*

# Copy project files
COPY pyproject.toml README.md ./
COPY src ./src

# Install the application
RUN pip install --upgrade pip && \
    pip install --no-cache-dir .

# Create a non-root user and ensure writable data directory
RUN groupadd --system appuser && useradd --system --gid appuser --home /app appuser && \
    mkdir -p /app/data && chown -R appuser:appuser /app
USER appuser

EXPOSE 8765

# Start the ASGI server. Override PORT/ENV_FILE with `docker run -e`.
CMD ["sh", "-c", "uvicorn app.asgi:app --host 0.0.0.0 --port ${PORT:-8765}"]
