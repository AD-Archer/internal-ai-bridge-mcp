"""MCP server wiring."""

from __future__ import annotations

import httpx
import json
import logging
import time
import uuid
from typing import Any
import asyncio

import uvicorn
from mcp.server.fastmcp import FastMCP
from mcp.server.websocket import websocket_server
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse, Response, StreamingResponse
from starlette.routing import Route, WebSocketRoute
from starlette.websockets import WebSocket
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware

from .ai_client import AIWebhookClient, AIWebhookError
from .config import Settings

logger = logging.getLogger(__name__)

# Global storage for callback messages (in production, use a database)
callback_messages = []

# Pending responses for OpenAI compatible endpoint
pending_responses: dict[str, asyncio.Queue] = {}


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
        "or by specifying an explicit URL. "
        "Check `ninjacat://messages` for any follow-up messages sent by the AI via callback."
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

    @mcp.resource("ninjacat://messages")
    def list_callback_messages() -> str:
        """Return any follow-up messages sent by the AI via the /callback endpoint."""
        return json.dumps(callback_messages, indent=2)

    return mcp


async def run_stdio(settings: Settings) -> None:
    """Run the server over stdio (for OpenWebUI adapters)."""
    server = build_server(settings)
    await server.run_stdio_async()


def _build_websocket_app(server: FastMCP, settings: Settings, client: AIWebhookClient | None = None) -> Starlette:
    async def health(_: Request) -> Response:
        return JSONResponse({"status": "ok"})

    async def index(_: Request) -> Response:
        return PlainTextResponse("Ninjacat MCP Bridge WebSocket endpoint at /mcp/openai.")

    async def callback(request: Request) -> Response:
        """Endpoint for AI to send follow-up messages."""
        try:
            data = await request.json()
            if not isinstance(data, dict):
                return JSONResponse({"error": "Invalid JSON"}, status_code=400)
            
            # Optional validation for status if present
            if "status" in data and data["status"] not in ["info", "success", "error", "complete"]:
                return JSONResponse({"error": "Invalid status"}, status_code=400)
            
            callback_messages.append(data)
            
            # Put into pending response queue if sessionID matches
            if "sessionID" in data and data["sessionID"] in pending_responses:
                await pending_responses[data["sessionID"]].put(data)
            
            # Send to frontend webhook if configured
            if settings.frontend_webhook_url:
                async with httpx.AsyncClient() as http_client:
                    try:
                        response = await http_client.post(
                            str(settings.frontend_webhook_url),
                            json=data,
                            timeout=200.0,
                        )
                        if response.status_code >= 400:
                            logger.error(
                                "Frontend webhook %s returned %s: %s",
                                settings.frontend_webhook_url,
                                response.status_code,
                                response.text,
                            )
                        else:
                            logger.info(
                                "Sent callback to frontend %s (status %s)",
                                settings.frontend_webhook_url,
                                response.status_code,
                            )
                    except Exception as exc:
                        logger.error("Failed to send callback to frontend: %s", exc)
            
            logger.info("Received callback message: %s", data)
            return JSONResponse({"status": "received"})
        except Exception as exc:
            logger.error("Callback error: %s", exc)
            return JSONResponse({"error": "Failed to process callback"}, status_code=500)

    async def mcp_ws(websocket: WebSocket) -> None:
        async with websocket_server(websocket.scope, websocket.receive, websocket.send) as streams:
            await server._mcp_server.run(  # noqa: SLF001 - accessing private attr for transport wiring
                streams[0],
                streams[1],
                server._mcp_server.create_initialization_options(),
            )

    async def openapi(request: Request) -> Response:
        base_url = str(request.base_url).rstrip("/")
        schema = {
            "openapi": "3.0.3",
            "info": {
                "title": "Ninjacat MCP Bridge",
                "version": "0.1.0",
                "description": (
                    "Minimal OpenAPI description exposing health checks for the Ninjacat MCP bridge. "
                    "The actual MCP interaction occurs over the WebSocket endpoint documented in the "
                    "x-mcp extension."
                ),
            },
            "servers": [{"url": base_url}],
            "paths": {
                "/healthz": {
                    "get": {
                        "summary": "Service health check",
                        "responses": {
                            "200": {
                                "description": "Service healthy",
                                "content": {
                                    "application/json": {
                                        "schema": {
                                            "type": "object",
                                            "properties": {
                                                "status": {"type": "string"},
                                            },
                                        }
                                    }
                                },
                            }
                        },
                    }
                }
            },
            "components": {},
            "x-mcp": {
                "transport": "websocket",
                "endpoint": f"{base_url}/mcp/openai",
                "notes": "Clients should open a WebSocket connection using the MCP subprotocol."
            },
        }
        headers = {
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET, OPTIONS",
            "Access-Control-Allow-Headers": "*",
        }

        if request.method == "OPTIONS":
            return Response(status_code=204, headers=headers)

        return JSONResponse(schema, headers=headers)

    async def openai_openapi(request: Request) -> Response:
        """Return a minimal OpenAPI spec for the chat completions endpoint."""
        base_url = str(request.base_url).rstrip("/")
        schema = {
            "openapi": "3.0.3",
            "info": {
                "title": "Ninjacat Chat Completions",
                "version": "1.0.0",
                "description": "OpenAI-compatible chat completions API"
            },
            "servers": [{"url": base_url}],
            "paths": {
                "/v1/chat/completions": {
                    "post": {
                        "summary": "Create chat completion",
                        "requestBody": {
                            "required": True,
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {
                                            "messages": {
                                                "type": "array",
                                                "items": {
                                                    "type": "object",
                                                    "properties": {
                                                        "role": {"type": "string"},
                                                        "content": {"type": "string"}
                                                    }
                                                }
                                            },
                                            "stream": {"type": "boolean"}
                                        }
                                    }
                                }
                            },
                            "responses": {
                                "200": {
                                    "description": "Successful response",
                                    "content": {
                                        "application/json": {
                                            "schema": {"type": "object"}
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
        return JSONResponse(schema)

    async def openai_models(request: Request) -> Response:
        """Return list of available models in OpenAI format."""
        models = {
            "object": "list",
            "data": [
                {
                    "id": "ninjacat",
                    "object": "model",
                    "created": 1640995200,
                    "owned_by": "ninjacat"
                }
            ]
        }
        return JSONResponse(models)

    async def openai_chat(request: Request) -> Response:
        if not client:
            return JSONResponse({"error": "Client not configured"}, status_code=500)
        try:
            data = await request.json()
            logger.info("Received OpenAI chat request: %s", data)
            messages = data.get("messages", [])
            if not messages:
                return JSONResponse({"error": "No messages"}, status_code=400)
            
            # Get the last user message
            prompt = ""
            for msg in reversed(messages):
                if msg.get("role") == "user":
                    prompt = msg.get("content", "")
                    break
            if not prompt:
                return JSONResponse({"error": "No user message"}, status_code=400)
            
            # Append instruction for the AI to respond via webhook
            prompt += " **NOTICE: this is an automated message, this message has been sent using a webhook. please respond using your webhook tool**"
            
            conversation_id = str(uuid.uuid4())
            queue = asyncio.Queue()
            pending_responses[conversation_id] = queue
            
            payload = {"prompt": prompt, "sessionID": conversation_id}
            logger.info("Sending to backend: %s", payload)
            await client.start_message(payload)
            
            # Wait for response
            try:
                response_data = await asyncio.wait_for(queue.get(), timeout=4120.0)
                logger.info("Received response from backend: %s", response_data)
            except asyncio.TimeoutError:
                if conversation_id in pending_responses:
                    del pending_responses[conversation_id]
                logger.error("Timeout waiting for callback from backend")
                return JSONResponse({"error": {"message": "Backend did not respond within timeout period. Please try again.", "type": "timeout"}}, status_code=504)
            
            if conversation_id in pending_responses:
                del pending_responses[conversation_id]
            
            # Format as proper OpenAI chat completion response
            content = response_data.get("message", "")
            
            # Return proper OpenAI-compatible response format
            response_obj = {
                "id": f"chatcmpl-{conversation_id}",
                "object": "chat.completion",
                "created": int(time.time()),
                "model": "ninjacat",
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": content
                        },
                        "finish_reason": "stop"
                    }
                ],
                "usage": {
                    "prompt_tokens": len(prompt.split()),
                    "completion_tokens": len(content.split()),
                    "total_tokens": len(prompt.split()) + len(content.split())
                }
            }
            logger.info("Returning OpenAI response: %s", response_obj)
            return JSONResponse(response_obj)
        except Exception as exc:
            logger.error("OpenAI chat error: %s", exc)
            return JSONResponse({"error": "Internal error"}, status_code=500)

    routes = [
        Route("/", index),
        Route("/healthz", health),
        Route("/callback", callback, methods=["POST"]),
        Route("/mcp/openapi.json", openapi),
        Route("/v1/chat/completions", openai_chat, methods=["POST"]),
        Route("/v1/chat/completions/openapi.json", openai_openapi),
        Route("/v1/models", openai_models),
        Route("/mcp/openai/v1/chat/completions", openai_chat, methods=["POST"]),
        WebSocketRoute("/mcp/openai", mcp_ws),
    ]
    middleware = [
        Middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_methods=["*"],
            allow_headers=["*"],
        )
    ]
    return Starlette(routes=routes, middleware=middleware)


async def run_websocket(settings: Settings, host: str = "0.0.0.0", port: int = 8765) -> None:
    """Run the server over WebSocket for clients that need it."""
    server = build_server(settings)
    app = _build_websocket_app(server)

    log_level = getattr(server.settings, "log_level", "INFO").lower()
    config = uvicorn.Config(app, host=host, port=port, log_level=log_level)
    uvicorn_server = uvicorn.Server(config)
    await uvicorn_server.serve()
