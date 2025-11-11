"""Building blocks shared by the MCP server wiring."""

from .apps import _build_memory_websocket_app, _build_websocket_app
from .middleware import build_auth_middleware, build_middleware
from .mcp import build_server, run_stdio
from .response_handler import build_response_handler
from .state import callback_messages, pending_responses

__all__ = [
    "_build_memory_websocket_app",
    "_build_websocket_app",
    "build_auth_middleware",
    "build_middleware",
    "build_server",
    "build_response_handler",
    "callback_messages",
    "pending_responses",
    "run_stdio",
]
