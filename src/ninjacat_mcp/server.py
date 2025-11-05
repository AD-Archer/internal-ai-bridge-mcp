"""MCP server wiring."""

from __future__ import annotations

import json
import logging
from typing import Any

import uvicorn
from mcp.server.fastmcp import Context, FastMCP
from mcp.server.websocket import websocket_server
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse, Response
from starlette.routing import Route, WebSocketRoute
from starlette.websockets import WebSocket

from .ai_client import AIWebhookClient, AIWebhookError
from .config import Settings

logger = logging.getLogger(__name__)


def build_server(settings: Settings, client: AIWebhookClient | None = None) -> FastMCP:
    """Construct an MCP server instance."""
    ai_client = client or AIWebhookClient(
        str(settings.ai_webhook_url),
        api_key=settings.ai_api_key,
        timeout=settings.ai_timeout,
    )

    instructions = (
        "You are connected to the Ninjacat MCP bridge. "
        "Use the `start_ai_message` tool to send prompts to the in-house AI webhook. "
        "Use `trigger_webhook` to reach any additional named webhooks defined in configuration "
        "or by specifying an explicit URL."
    )

    mcp = FastMCP(
        name="Ninjacat MCP Bridge",
        instructions=instructions,
        website_url="https://openwebui.com",
    )

    def _format_payload(**kwargs: Any) -> dict[str, Any]:
        return {key: value for key, value in kwargs.items() if value is not None}

    @mcp.tool()
    async def start_ai_message(
        prompt: str,
        *,
        conversation_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        attachments: list[dict[str, Any]] | None = None,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Send a prompt to the in-house AI webhook and return its response."""
        payload = _format_payload(
            prompt=prompt,
            conversation_id=conversation_id,
            metadata=metadata,
            attachments=attachments,
            extra=extra,
        )
        logger.debug("Dispatching start_ai_message payload: %s", payload)
        try:
            return await ai_client.start_message(payload)
        except AIWebhookError as exc:
            logger.error("AI webhook error: %s", exc)
            raise

    @mcp.tool()
    async def trigger_webhook(
        target: str,
        *,
        payload: dict[str, Any] | None = None,
        method: str | None = None,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Invoke a configured webhook (or absolute URL) with the supplied payload."""
        payload = payload or {}
        headers = headers or {}

        if target in settings.extra_webhooks:
            target_cfg = settings.extra_webhooks[target]
            merged_headers = {**target_cfg.headers, **headers}
            logger.debug("Triggering named webhook '%s' via %s", target, target_cfg.url)
            return await ai_client.trigger_webhook(
                str(target_cfg.url),
                payload,
                method=method or target_cfg.method,
                headers=merged_headers,
                secret=target_cfg.secret,
            )

        logger.debug("Triggering ad-hoc webhook at %s", target)
        return await ai_client.trigger_webhook(
            target,
            payload,
            method=method or "POST",
            headers=headers,
        )

    @mcp.tool()
    async def call_ai_and_webhook(
        prompt: str,
        *,
        webhook_target: str | None = None,
        webhook_payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Convenience tool that first sends the AI prompt and optionally dispatches a follow-up webhook.
        """
        ai_response = await start_ai_message(prompt)

        if webhook_target:
            await trigger_webhook(
                webhook_target,
                payload=webhook_payload or {"ai_response": ai_response},
            )

        return ai_response

    @mcp.resource("ninjacat://webhooks")
    def list_webhooks() -> str:
        """Expose configured webhook targets to the client."""
        summary = {
            name: {
                "url": str(target.url),
                "method": target.method,
                "headers": target.headers,
                "has_secret": bool(target.secret),
            }
            for name, target in settings.extra_webhooks.items()
        }
        return json.dumps(summary, indent=2)

    return mcp


async def run_stdio(settings: Settings) -> None:
    """Run the server over stdio (for OpenWebUI adapters)."""
    server = build_server(settings)
    await server.run_stdio_async()


def _build_websocket_app(server: FastMCP) -> Starlette:
    async def health(_: Request) -> Response:
        return JSONResponse({"status": "ok"})

    async def index(_: Request) -> Response:
        return PlainTextResponse("Ninjacat MCP Bridge WebSocket endpoint at /mcp.")

    async def mcp_ws(websocket: WebSocket) -> None:
        async with websocket_server(websocket.scope, websocket.receive, websocket.send) as streams:
            await server._mcp_server.run(  # noqa: SLF001 - accessing private attr for transport wiring
                streams[0],
                streams[1],
                server._mcp_server.create_initialization_options(),
            )

    routes = [
        Route("/", index),
        Route("/healthz", health),
        WebSocketRoute("/mcp", mcp_ws),
    ]
    return Starlette(routes=routes)


async def run_websocket(settings: Settings, host: str = "0.0.0.0", port: int = 8765) -> None:
    """Run the server over WebSocket for clients that need it."""
    server = build_server(settings)
    app = _build_websocket_app(server)

    log_level = getattr(server.settings, "log_level", "INFO").lower()
    config = uvicorn.Config(app, host=host, port=port, log_level=log_level)
    uvicorn_server = uvicorn.Server(config)
    await uvicorn_server.serve()
