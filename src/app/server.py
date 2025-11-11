"""MCP server wiring."""
from __future__ import annotations

import logging

import uvicorn

from .ai_client import AIWebhookClient
from .config import Settings
from .server_components.apps import _build_memory_websocket_app, _build_websocket_app
from .server_components.mcp import build_server, run_stdio

logger = logging.getLogger(__name__)

__all__ = [
    "build_server",
    "run_stdio",
    "_build_websocket_app",
    "_build_memory_websocket_app",
    "run_websocket",
    "run_memory_websocket",
]


async def run_websocket(
    settings: Settings,
    host: str = "0.0.0.0",
    port: int = 8765,
    client: AIWebhookClient | None = None,
) -> None:
    """Run the combined MCP + OpenAI-compatible server over WebSocket."""
    server = build_server(settings, client=client)
    app = _build_websocket_app(server, settings, client=client)

    log_level = getattr(settings, "log_level", "INFO").lower()
    config = uvicorn.Config(app, host=host, port=port, log_level=log_level)
    uvicorn_server = uvicorn.Server(config)
    await uvicorn_server.serve()


async def run_memory_websocket(settings: Settings, host: str = "0.0.0.0", port: int = 8765) -> None:
    """Run only the memory MCP surface over WebSocket."""
    app = _build_memory_websocket_app(settings)

    log_level = getattr(settings, "log_level", "INFO").lower()
    config = uvicorn.Config(app, host=host, port=port, log_level=log_level)
    uvicorn_server = uvicorn.Server(config)
    await uvicorn_server.serve()
