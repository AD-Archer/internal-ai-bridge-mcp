FROM python:3.11-slim

# Prevent Python from writing .pyc files and buffer logs
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    ENV_FILE=/app/.env \
    PORT=8765

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

# Create a non-root user to run the service
RUN groupadd --system appuser && useradd --system --gid appuser --home /app appuser
USER appuser

EXPOSE 8765

# Start the ASGI server. Override PORT/ENV_FILE with `docker run -e`.
CMD ["sh", "-c", "uvicorn app.asgi:app --host 0.0.0.0 --port ${PORT:-8765}"]
