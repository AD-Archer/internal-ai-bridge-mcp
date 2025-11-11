"""MCP server wiring."""

from __future__ import annotations

import httpx
import json
import logging
import time
import uuid
from typing import Any, Awaitable, Callable
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
from .auth import BearerAuthMiddleware

logger = logging.getLogger(__name__)

# Global storage for callback messages (in production, use a database)
callback_messages = []

# Pending responses for OpenAI compatible endpoint
pending_responses: dict[str, asyncio.Queue] = {}


def _build_auth_middleware(settings: Settings, *, exempt_paths: set[str] | None = None) -> Middleware | None:
    if not settings.bearer_auth_enabled:
        return None

    tokens = {path: token for path, token in settings.route_bearer_tokens.items() if token}
    default_token = settings.default_bearer_token or None
    if not default_token and not tokens:
        logger.warning("Bearer auth is enabled but no tokens were configured; skipping middleware.")
        return None

    return Middleware(
        BearerAuthMiddleware,
        enabled=settings.bearer_auth_enabled,
        default_token=default_token,
        route_tokens=tokens,
        exempt_paths=sorted(exempt_paths or set()),
    )


def _build_middleware(settings: Settings, *, exempt_paths: set[str] | None = None) -> list[Middleware]:
    middleware: list[Middleware] = []
    auth_middleware = _build_auth_middleware(settings, exempt_paths=exempt_paths)
    if auth_middleware:
        middleware.append(auth_middleware)
    middleware.append(
        Middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_methods=["*"],
            allow_headers=["*"],
        )
    )
    return middleware


def _build_response_handler(settings: Settings) -> Callable[[dict[str, Any]], Awaitable[None]]:
    """Create a coroutine that fans out recorded responses to listeners."""

    async def handle(record: dict[str, Any]) -> None:
        payload = dict(record.get("payload") or {})
        session_id = record.get("session_id")
        logger.info("🎯 Response handler called with: session_id=%s, payload=%s", session_id, payload)

        callback_messages.append(payload)
        logger.info("📝 Added to callback_messages, total count: %d", len(callback_messages))

        if session_id and session_id in pending_responses:
            logger.info("📋 Putting response in pending queue for session %s", session_id)
            await pending_responses[session_id].put(payload)
        elif session_id:
            logger.warning("⚠️ Session %s not found in pending_responses. Keys: %s", session_id, list(pending_responses.keys()))
        else:
            logger.warning("⚠️ No session_id in record")

        if settings.frontend_webhook_url:
            logger.info("🔗 Sending to frontend webhook: %s", settings.frontend_webhook_url)
            async with httpx.AsyncClient() as http_client:
                try:
                    response = await http_client.post(
                        str(settings.frontend_webhook_url),
                        json=payload,
                        timeout=200.0,
                    )
                    if response.status_code >= 400:
                        logger.error(
                            "❌ Frontend webhook %s returned %s: %s",
                            settings.frontend_webhook_url,
                            response.status_code,
                            response.text,
                        )
                    else:
                        logger.info(
                            "✅ Sent callback to frontend %s (status %s)",
                            settings.frontend_webhook_url,
                            response.status_code,
                        )
                except Exception as exc:
                    logger.error("❌ Failed to send callback to frontend: %s", exc)
        else:
            logger.info("ℹ️ No frontend_webhook_url configured")

    return handle


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
        "When you receive a response from the AI, ALWAYS call the `send_user_response` MCP tool to send it back. "
        "This records the response in conversation memory AND sends it back to the client. "
        "Check `external-ai://messages` for follow-up messages recorded via the memory MCP surface."
    )

    mcp = FastMCP(
        name="external-ai MCP Bridge",
        instructions=instructions,
        website_url="https://openwebui.com",
    )

    # Also expose conversation memory tools/resources via the same MCP server
    response_handler = _build_response_handler(settings)
    try:
        store = ConversationStore(settings.conversation_db_path)
        register_memory_mcp_surface(mcp, store, settings, response_handler=response_handler)
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
        """Return any follow-up messages captured via the response-recording MCP tool."""
        return json.dumps(callback_messages, indent=2)

    return mcp


async def run_stdio(settings: Settings) -> None:
    """Run the server over stdio (for OpenWebUI adapters)."""
    server = build_server(settings)
    await server.run_stdio_async()


def _build_websocket_app(server: FastMCP, settings: Settings, client: AIWebhookClient | None = None) -> Starlette:
    store = ConversationStore(settings.conversation_db_path)
    response_handler = _build_response_handler(settings)
    
    # Clean up old messages on startup
    try:
        deleted_count = store.delete_old_messages(settings.message_retention_days)
        if deleted_count > 0:
            logger.info("Cleaned up %d old messages (older than %d days)", deleted_count, settings.message_retention_days)
    except Exception as exc:
        logger.warning("Failed to clean up old messages: %s", exc)
    
    memory_server = build_memory_server(store, settings, response_handler=response_handler)
    memory_service = MemoryService(store, settings)

    async def health(_: Request) -> Response:
        return JSONResponse({"status": "ok"})

    async def index(_: Request) -> Response:
        return PlainTextResponse("external-ai MCP Bridge WebSocket endpoints at /mcp/openai and /mcp/hook.")

    async def callback(request: Request) -> Response:
        """Endpoint for AI to send follow-up messages."""
        try:
            data = await request.json()
        except Exception as exc:
            logger.error("Callback failed to parse JSON: %s", exc)
            return JSONResponse({"error": "Invalid JSON"}, status_code=400)

        if not isinstance(data, dict):
            logger.error("Callback received non-dict data: %s", type(data))
            return JSONResponse({"error": "Invalid JSON"}, status_code=400)

        logger.info("🔄 Callback received from AI: %s", data)
        try:
            record = memory_service.record_ai_response(payload=data)
            logger.info("✅ Recorded AI response: %s", record)
        except ValueError as exc:
            logger.error("❌ Callback validation error: %s", exc)
            return JSONResponse({"error": str(exc)}, status_code=400)
        except Exception as exc:
            logger.error("❌ Callback error while storing message: %s", exc)
            return JSONResponse({"error": "Failed to process callback"}, status_code=500)

        logger.info("📤 Dispatching response via handler")
        await response_handler(record)
        logger.info("✅ Callback message received and dispatched: %s", data)
        return JSONResponse({"status": "received", "session_id": record["session_id"]})

    async def mcp_memory_ws(websocket: WebSocket) -> None:
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
                f" **NOTICE: this is an automated message sent via webhook. "
                f"When you have a response, you MUST call the `send_user_response` MCP tool with your response. "
                f"This is the ONLY way to send your response back to the user and OpenWebUI. "
                f"Available memory MCP tools: list_conversations, get_conversation, recall_conversation_context, send_user_response. "
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
                    },
                    {
                        "name": "send_user_response",
                        "description": "Send the AI response back to the user and OpenWebUI. MUST be called with your response message after receiving a prompt. This records the response in conversation memory and sends it to the client.",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "session_id": {"type": ["string", "null"], "description": "Session ID to record response in"},
                                "message": {"type": ["string", "null"], "description": "The response message content from the AI"},
                                "payload": {"type": ["object", "null"], "description": "Additional payload data"},
                                "role": {"type": ["string", "null"], "description": "Role of the message sender (defaults to 'user')"},
                                "status": {"type": ["string", "null"], "description": "Status of the response"}
                            },
                            "required": ["message"]
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
                    elif tool_name == "send_user_response":
                        session_id = tool_args.get("session_id")
                        message = tool_args.get("message")
                        payload = tool_args.get("payload")
                        role = tool_args.get("role") or "user"
                        status = tool_args.get("status")
                        logger.info("📨 AI called send_user_response tool: session_id=%s, message=%s, role=%s, status=%s", session_id, message, role, status)
                        result = service.record_ai_response(
                            session_id=session_id,
                            message=message,
                            payload=payload,
                            role=role,
                            status=status,
                        )
                        logger.info("✅ Recorded AI response via tool: %s", result)
                        # Dispatch the response to OpenWebUI
                        logger.info("📤 Dispatching AI response via handler")
                        await response_handler(result)
                        logger.info("✅ AI response dispatched successfully")
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
        Route("/mcp/hook", mcp_memory_http, methods=["POST"]),
        WebSocketRoute("/mcp/openai", mcp_ws),
        WebSocketRoute("/mcp/hook", mcp_memory_ws),
    ] + memory_routes
    middleware = _build_middleware(settings, exempt_paths={"/healthz"})

    return Starlette(routes=routes, middleware=middleware)


def _build_memory_websocket_app(settings: Settings) -> Starlette:
    store = ConversationStore(settings.conversation_db_path)
    response_handler = _build_response_handler(settings)
    
    # Clean up old messages on startup
    try:
        deleted_count = store.delete_old_messages(settings.message_retention_days)
        if deleted_count > 0:
            logger.info("Cleaned up %d old messages (older than %d days)", deleted_count, settings.message_retention_days)
    except Exception as exc:
        logger.warning("Failed to clean up old messages: %s", exc)
    
    memory_server = build_memory_server(store, settings, response_handler=response_handler)

    async def health(_: Request) -> Response:
        return JSONResponse({"status": "ok"})

    async def index(_: Request) -> Response:
        return PlainTextResponse("Memory MCP server WebSocket endpoint at /mcp/hook.")

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
                    },
                    {
                        "name": "send_user_response",
                        "description": "Send the AI response back to the user and OpenWebUI. MUST be called with your response message after receiving a prompt. This records the response in conversation memory and sends it to the client.",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "session_id": {"type": ["string", "null"], "description": "Session ID to record response in"},
                                "message": {"type": ["string", "null"], "description": "The response message content from the AI"},
                                "payload": {"type": ["object", "null"], "description": "Additional payload data"},
                                "role": {"type": ["string", "null"], "description": "Role of the message sender (defaults to 'user')"},
                                "status": {"type": ["string", "null"], "description": "Status of the response"}
                            },
                            "required": ["message"]
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
                
                service = MemoryService(store, settings)
                
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
                    elif tool_name == "send_user_response":
                        session_id = tool_args.get("session_id")
                        message = tool_args.get("message")
                        payload = tool_args.get("payload")
                        role = tool_args.get("role") or "user"
                        status = tool_args.get("status")
                        logger.info("📨 AI called send_user_response tool: session_id=%s, message=%s, role=%s, status=%s", session_id, message, role, status)
                        result = service.record_ai_response(
                            session_id=session_id,
                            message=message,
                            payload=payload,
                            role=role,
                            status=status,
                        )
                        logger.info("✅ Recorded AI response via tool: %s", result)
                        # Dispatch the response to OpenWebUI
                        logger.info("📤 Dispatching AI response via handler")
                        await response_handler(result)
                        logger.info("✅ AI response dispatched successfully")
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
        Route("/mcp/hook", mcp_memory_http, methods=["POST"]),
        WebSocketRoute("/mcp/hook", mcp_memory_ws),
    ] + memory_routes
    middleware = _build_middleware(settings, exempt_paths={"/healthz"})
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
