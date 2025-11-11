#!/bin/bash

# Script to run the External AI MCP server using UV and uvicorn
# Assumes .env file is in the project root with AI_WEBHOOK_URL set

set -e  # Exit on any error

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$PROJECT_DIR/.venv"

echo "Starting External AI MCP server..."
echo "Project dir: $PROJECT_DIR"
echo "Virtual env: $VENV_DIR"

# Check if venv exists
if [ ! -d "$VENV_DIR" ]; then
    echo "Error: Virtual environment not found at $VENV_DIR"
    echo "Run 'uv venv && source .venv/bin/activate && uv pip install -e .' first"
    exit 1
fi

# Activate venv and run server
cd "$PROJECT_DIR"
source "$VENV_DIR/bin/activate"
export ENV_FILE=.env

echo "Loading config from .env..."
echo "Starting uvicorn server on http://0.0.0.0:8765 (reload enabled)..."
echo "MCP WebSocket endpoints: ws://0.0.0.0:8765/mcp/openai (main) and ws://0.0.0.0:8765/mcp/memory (memory-only)"
uvicorn app.asgi:app --host 0.0.0.0 --port 8765 --reload