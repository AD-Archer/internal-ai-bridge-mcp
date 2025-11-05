"""ASGI app entrypoint for running with uvicorn.

This module exposes a top-level `app` variable so you can run:

    uvicorn ninjacat_mcp.asgi:app --host 0.0.0.0 --port 8765

It will attempt to load configuration from the environment (or a `.env` file
if you export `ENV_FILE` or create one in the project root). If required
settings are missing, a minimal app exposing `/healthz` is provided that
returns a helpful message.
"""
from __future__ import annotations

import os
import logging
from typing import Optional

from starlette.applications import Starlette
from starlette.routing import Route, WebSocketRoute
from starlette.responses import JSONResponse, PlainTextResponse, Response

from .config import load_settings, SettingsError
from .server import build_server, _build_websocket_app
from .ai_client import AIWebhookClient

logger = logging.getLogger(__name__)


def _make_fallback_app(error: Exception) -> Starlette:
    async def health(_: object) -> Response:  # Request is unused
        return JSONResponse({"status": "error", "detail": str(error)})

    async def index(_: object) -> Response:
        msg = (
            "Ninjacat MCP Bridge is not configured. "
            "Set AI_WEBHOOK_URL in the environment or provide an .env file."
        )
        return PlainTextResponse(msg)

    routes = [Route("/", index), Route("/healthz", health)]
    return Starlette(routes=routes)


def create_app(env_file: Optional[str] = None) -> Starlette:
    """Create the Starlette ASGI app.

    If `env_file` is provided, it will be passed to the settings loader.
    """
    try:
        settings = load_settings(env_file=env_file) if env_file else load_settings()
    except SettingsError as exc:
        logger.warning("Failed to load settings for ASGI app: %s", exc)
        return _make_fallback_app(exc)

    server = build_server(settings)
    client = AIWebhookClient(
        str(settings.ai_webhook_url),
        api_key=settings.ai_api_key,
        timeout=settings.ai_timeout,
    )
    return _build_websocket_app(server, settings, client)


# Allow callers to override via ENV_FILE if they want to load a dotenv file
env_file = os.environ.get("ENV_FILE")
try:
    app = create_app(env_file=env_file)
except Exception as exc:  # pragma: no cover - defensive fallback
    logger.exception("Unhandled error while creating ASGI app: %s", exc)
    app = _make_fallback_app(exc)
