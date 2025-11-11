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
from .storage import ConversationStore, format_history_for_prompt
from .memory_api import build_memory_routes, register_memory_mcp_surface, build_memory_server, MemoryService

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
        "You are connected to the external-ai MCP bridge. "
        "Use the `start_ai_message` tool to send prompts to the in-house AI webhook. "
        "Use `trigger_webhook` to reach any additional named webhooks defined in configuration "
        "or by specifying an explicit URL. "
        "Check `external-ai://messages` for any follow-up messages sent by the AI via callback."
    )

    mcp = FastMCP(
        name="external-ai MCP Bridge",
        instructions=instructions,
        website_url="https://openwebui.com",
    )

    # Also expose conversation memory tools/resources via the same MCP server
    try:
        store = ConversationStore(settings.conversation_db_path)
        register_memory_mcp_surface(mcp, store, settings)
    except Exception as exc:
        # Defensive: memory surface should never prevent core server from running
        logger.warning("Failed to register memory MCP surface: %s", exc)

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

    @mcp.resource("external-ai://webhooks")
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

    @mcp.resource("external-ai://messages")
    def list_callback_messages() -> str:
        """Return any follow-up messages sent by the AI via the /callback endpoint."""
        return json.dumps(callback_messages, indent=2)

    return mcp


async def run_stdio(settings: Settings) -> None:
    """Run the server over stdio (for OpenWebUI adapters)."""
    server = build_server(settings)
    await server.run_stdio_async()


def _build_websocket_app(server: FastMCP, settings: Settings, client: AIWebhookClient | None = None) -> Starlette:
    store = ConversationStore(settings.conversation_db_path)
    
    # Clean up old messages on startup
    try:
        deleted_count = store.delete_old_messages(settings.message_retention_days)
        if deleted_count > 0:
            logger.info("Cleaned up %d old messages (older than %d days)", deleted_count, settings.message_retention_days)
    except Exception as exc:
        logger.warning("Failed to clean up old messages: %s", exc)
    
    memory_server = build_memory_server(store, settings)

    async def health(_: Request) -> Response:
        return JSONResponse({"status": "ok"})

    async def index(_: Request) -> Response:
        return PlainTextResponse("external-ai MCP Bridge WebSocket endpoints at /mcp/openai and /mcp/memory.")

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
            session_id = data.get("sessionID") or data.get("session_id")
            assistant_message = data.get("message") or data.get("payload_summary")
            if session_id and (assistant_message or data):
                try:
                    store.record_message(
                        session_id,
                        "assistant",
                        assistant_message or json.dumps(data),
                        metadata=data,
                    )
                except Exception as exc:
                    logger.error("Failed to store assistant message: %s", exc)
            
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

    async def mcp_memory_ws(websocket: WebSocket) -> None:
        memory_server = build_memory_server(store, settings)
        async with websocket_server(websocket.scope, websocket.receive, websocket.send) as streams:
            await memory_server._mcp_server.run(  # noqa: SLF001 - accessing private attr for transport wiring
                streams[0],
                streams[1],
                memory_server._mcp_server.create_initialization_options(),
            )

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
                "title": "external-ai MCP Bridge",
                "version": "0.1.0",
                "description": (
                    "Minimal OpenAPI description exposing health checks for the external-ai MCP bridge. "
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
                "title": "external-ai Chat Completions",
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
                    "id": settings.model_name,
                    "object": "model",
                    "created": 1640995200,
                    "owned_by": "Antonio Archer Custom MCP server"
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

            supplied_session = (
                data.get("session_id")
                or data.get("sessionID")
                or data.get("conversation_id")
            )
            session_id = supplied_session or str(uuid.uuid4())

            history = store.get_messages(session_id, limit=settings.conversation_history_limit)
            history_text = ""
            if history:
                history_text = format_history_for_prompt(history)
            notice = (
                f" **NOTICE: this is an automated message, this message has been sent using a "
                f"webhook. please respond using your webhook tool. "
                f"You have access to memory MCP tools: list_conversations, get_conversation, recall_conversation_context. "
                f"Current conversation_id/session_id: {session_id}**"
            )
            final_prompt = prompt
            if history_text:
                final_prompt = (
                    "Conversation history to help you stay consistent:\n"
                    f"{history_text}\n\n"
                    f"Latest user message:\n{prompt}"
                )
            final_prompt = f"{final_prompt}{notice}"

            queue = asyncio.Queue()
            pending_responses[session_id] = queue

            try:
                store.record_message(
                    session_id,
                    "user",
                    prompt,
                    metadata={"source": "openai_chat"},
                )
            except Exception as exc:
                logger.error("Failed to store user prompt: %s", exc)

            payload = {"prompt": final_prompt, "sessionID": session_id}
            logger.info("Sending to backend: %s", payload)
            await client.start_message(payload)
            
            # Wait for response
            try:
                response_data = await asyncio.wait_for(queue.get(), timeout=4120.0)
                logger.info("Received response from backend: %s", response_data)
            except asyncio.TimeoutError:
                if session_id in pending_responses:
                    del pending_responses[session_id]
                logger.error("Timeout waiting for callback from backend")
                return JSONResponse({"error": {"message": "Backend did not respond within timeout period. Please try again.", "type": "timeout"}}, status_code=504)
            
            if session_id in pending_responses:
                del pending_responses[session_id]
            
            # Format as proper OpenAI chat completion response
            content = response_data.get("message", "")
            
            # Return proper OpenAI-compatible response format
            response_obj = {
                "id": f"chatcmpl-{session_id}",
                "object": "chat.completion",
                "created": int(time.time()),
                "model": settings.model_name,
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

    async def mcp_memory_http(request: Request) -> Response:
        """Handle MCP protocol over HTTP using JSON-RPC for memory tools."""
        if request.method != "POST":
            return JSONResponse({"error": "Method not allowed"}, status_code=405)
        
        try:
            data = await request.json()
            if not isinstance(data, dict):
                return JSONResponse({"jsonrpc": "2.0", "error": {"code": -32700, "message": "Parse error"}}, status_code=400)
            
            method = data.get("method")
            params = data.get("params", {})
            id = data.get("id")
            
            # Handle notifications (no id)
            if id is None:
                logger.info("Received MCP notification: %s", method)
                return Response(status_code=204)
            
            if not method:
                return JSONResponse({"jsonrpc": "2.0", "id": id, "error": {"code": -32700, "message": "Parse error"}}, status_code=400)
            
            logger.info("MCP HTTP request method: %s, id: %s", method, id)
            
            service = MemoryService(store, settings)
            
            if method == "initialize":
                # Handle initialize
                response = {
                    "jsonrpc": "2.0",
                    "id": id,
                    "result": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {
                            "tools": {"listChanged": True},
                            "resources": {"listChanged": True}
                        },
                        "serverInfo": {
                            "name": "conversation-memory",
                            "version": "0.1.0"
                        }
                    }
                }
                return JSONResponse(response)
            
            elif method == "tools/list":
                # List memory tools
                tools = [
                    {
                        "name": "list_conversations",
                        "description": "Return the most recently updated sessions stored in the memory DB.",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "limit": {"type": ["integer", "null"], "description": "Maximum number of sessions to return"}
                            }
                        }
                    },
                    {
                        "name": "get_conversation",
                        "description": "Dump role/content/metadata for a session.",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "session_id": {"type": "string", "description": "Session ID to retrieve"},
                                "limit": {"type": ["integer", "null"], "description": "Maximum number of messages to return"}
                            },
                            "required": ["session_id"]
                        }
                    },
                    {
                        "name": "recall_conversation_context",
                        "description": "Return a context block plus separated user/assistant turns for a session.",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "session_id": {"type": "string", "description": "Session ID to recall"},
                                "limit": {"type": ["integer", "null"], "description": "Maximum number of messages to include"}
                            },
                            "required": ["session_id"]
                        }
                    },
                    {
                        "name": "delete_conversation",
                        "description": "Remove a stored session and all of its messages.",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "session_id": {"type": "string", "description": "Session ID to delete"}
                            },
                            "required": ["session_id"]
                        }
                    }
                ]
                response = {
                    "jsonrpc": "2.0",
                    "id": id,
                    "result": {"tools": tools}
                }
                return JSONResponse(response)
            
            elif method == "tools/call":
                # Call tool
                tool_name = params.get("name")
                tool_args = params.get("arguments", {})
                
                try:
                    if tool_name == "list_conversations":
                        limit = tool_args.get("limit")
                        result = {"sessions": service.list_sessions(limit=limit)}
                    elif tool_name == "get_conversation":
                        session_id = tool_args["session_id"]
                        limit = tool_args.get("limit")
                        result = service.conversation_detail(session_id, limit)
                    elif tool_name == "recall_conversation_context":
                        session_id = tool_args["session_id"]
                        limit = tool_args.get("limit")
                        result = service.recall_memory(session_id, limit)
                    elif tool_name == "delete_conversation":
                        session_id = tool_args["session_id"]
                        service.delete_session(session_id)
                        result = {"status": "deleted", "session_id": session_id}
                    else:
                        return JSONResponse({"jsonrpc": "2.0", "id": id, "error": {"code": -32601, "message": "Method not found"}}, status_code=404)
                    
                    response = {
                        "jsonrpc": "2.0",
                        "id": id,
                        "result": result
                    }
                    return JSONResponse(response)
                except Exception as exc:
                    logger.error("Tool call error: %s", exc)
                    return JSONResponse({"jsonrpc": "2.0", "id": id, "error": {"code": -32000, "message": str(exc)}}, status_code=500)
            
            elif method == "resources/list":
                # List memory resources
                resources = [
                    {
                        "uri": "memory://sessions",
                        "name": "Conversation Sessions",
                        "description": "List of all conversation sessions",
                        "mimeType": "application/json"
                    },
                    {
                        "uri": "memory://health",
                        "name": "Memory Service Health",
                        "description": "Health status of the memory service",
                        "mimeType": "application/json"
                    }
                ]
                response = {
                    "jsonrpc": "2.0",
                    "id": id,
                    "result": {"resources": resources}
                }
                return JSONResponse(response)
            
            elif method == "resources/read":
                # Read resource
                uri = params.get("uri")
                try:
                    if uri == "memory://sessions":
                        content = json.dumps({"sessions": service.list_sessions()}, indent=2)
                    elif uri == "memory://health":
                        content = json.dumps({"status": "ok", "conversation_limit": settings.conversation_history_limit}, indent=2)
                    else:
                        return JSONResponse({"jsonrpc": "2.0", "id": id, "error": {"code": -32602, "message": "Invalid params"}}, status_code=400)
                    
                    response = {
                        "jsonrpc": "2.0",
                        "id": id,
                        "result": {
                            "contents": [{
                                "uri": uri,
                                "mimeType": "application/json",
                                "text": content
                            }]
                        }
                    }
                    return JSONResponse(response)
                except Exception as exc:
                    logger.error("Resource read error: %s", exc)
                    return JSONResponse({"jsonrpc": "2.0", "id": id, "error": {"code": -32000, "message": str(exc)}}, status_code=500)
            
            else:
                return JSONResponse({"jsonrpc": "2.0", "id": id, "error": {"code": -32601, "message": "Method not found"}}, status_code=404)
        
        except Exception as exc:
            logger.error("MCP HTTP error: %s", exc)
            return JSONResponse({"jsonrpc": "2.0", "error": {"code": -32700, "message": "Parse error"}}, status_code=400)

    memory_routes = build_memory_routes(store, settings)

    routes = [
        Route("/", index),
        Route("/healthz", health),
        Route("/callback", callback, methods=["POST"]),
        Route("/mcp/openapi.json", openapi),
        Route("/v1/chat/completions", openai_chat, methods=["POST"]),
        Route("/v1/chat/completions/openapi.json", openai_openapi),
        Route("/v1/models", openai_models),
        Route("/mcp/openai/v1/chat/completions", openai_chat, methods=["POST"]),
        Route("/mcp/memory", mcp_memory_http, methods=["POST"]),
        WebSocketRoute("/mcp/openai", mcp_ws),
        WebSocketRoute("/mcp/memory", mcp_memory_ws),
    ] + memory_routes
    middleware = [
        Middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_methods=["*"],
            allow_headers=["*"],
        )
    ]

    return Starlette(routes=routes, middleware=middleware)


def _build_memory_websocket_app(settings: Settings) -> Starlette:
    store = ConversationStore(settings.conversation_db_path)
    
    # Clean up old messages on startup
    try:
        deleted_count = store.delete_old_messages(settings.message_retention_days)
        if deleted_count > 0:
            logger.info("Cleaned up %d old messages (older than %d days)", deleted_count, settings.message_retention_days)
    except Exception as exc:
        logger.warning("Failed to clean up old messages: %s", exc)
    
    memory_server = build_memory_server(store, settings)

    async def health(_: Request) -> Response:
        return JSONResponse({"status": "ok"})

    async def index(_: Request) -> Response:
        return PlainTextResponse("Memory MCP server WebSocket endpoint at /mcp/memory.")

    async def mcp_memory_http(request: Request) -> Response:
        """Handle MCP protocol over HTTP using JSON-RPC."""
        if request.method != "POST":
            return JSONResponse({"error": "Method not allowed"}, status_code=405)
        
        try:
            data = await request.json()
            if not isinstance(data, dict) or "method" not in data:
                return JSONResponse({"jsonrpc": "2.0", "error": {"code": -32700, "message": "Parse error"}}, status_code=400)
            
            method = data["method"]
            params = data.get("params", {})
            id = data.get("id")
            
            if method == "initialize":
                # Handle initialize
                response = {
                    "jsonrpc": "2.0",
                    "id": id,
                    "result": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {
                            "tools": {"listChanged": True}
                        },
                        "serverInfo": {
                            "name": "conversation-memory",
                            "version": "0.1.0"
                        }
                    }
                }
                return JSONResponse(response)
            
            elif method == "tools/list":
                # List tools
                tools = []
                for tool_name, tool in memory_server._mcp_server.tools.items():
                    tools.append({
                        "name": tool_name,
                        "description": tool.description,
                        "inputSchema": tool.inputSchema
                    })
                response = {
                    "jsonrpc": "2.0",
                    "id": id,
                    "result": {"tools": tools}
                }
                return JSONResponse(response)
            
            elif method == "tools/call":
                # Call tool
                tool_name = params.get("name")
                tool_args = params.get("arguments", {})
                if tool_name not in memory_server._mcp_server.tools:
                    return JSONResponse({"jsonrpc": "2.0", "id": id, "error": {"code": -32601, "message": "Method not found"}}, status_code=404)
                
                tool = memory_server._mcp_server.tools[tool_name]
                try:
                    result = await tool(**tool_args)
                    response = {
                        "jsonrpc": "2.0",
                        "id": id,
                        "result": result
                    }
                    return JSONResponse(response)
                except Exception as exc:
                    logger.error("Tool call error: %s", exc)
                    return JSONResponse({"jsonrpc": "2.0", "id": id, "error": {"code": -32000, "message": str(exc)}}, status_code=500)
            
            else:
                return JSONResponse({"jsonrpc": "2.0", "id": id, "error": {"code": -32601, "message": "Method not found"}}, status_code=404)
        
        except Exception as exc:
            logger.error("MCP HTTP error: %s", exc)
            return JSONResponse({"jsonrpc": "2.0", "error": {"code": -32700, "message": "Parse error"}}, status_code=400)

    async def mcp_memory_ws(websocket: WebSocket) -> None:
        async with websocket_server(websocket.scope, websocket.receive, websocket.send) as streams:
            await memory_server._mcp_server.run(  # noqa: SLF001 - accessing private attr for transport wiring
                streams[0],
                streams[1],
                memory_server._mcp_server.create_initialization_options(),
            )

    memory_routes = build_memory_routes(store, settings)

    routes = [
        Route("/", index),
        Route("/healthz", health),
        Route("/mcp/memory", mcp_memory_http, methods=["POST"]),
        WebSocketRoute("/mcp/memory", mcp_memory_ws),
    ] + memory_routes
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
    app = _build_websocket_app(server, settings)

    log_level = getattr(settings, "log_level", "INFO").lower()
    config = uvicorn.Config(app, host=host, port=port, log_level=log_level)
    uvicorn_server = uvicorn.Server(config)
    await uvicorn_server.serve()


async def run_memory_websocket(settings: Settings, host: str = "0.0.0.0", port: int = 8765) -> None:
    """Run the memory MCP server over WebSocket."""
    app = _build_memory_websocket_app(settings)

    log_level = getattr(settings, "log_level", "INFO").lower()
    config = uvicorn.Config(app, host=host, port=port, log_level=log_level)
    uvicorn_server = uvicorn.Server(config)
    await uvicorn_server.serve()
