"""Swagger UI and comprehensive OpenAPI documentation."""
from __future__ import annotations

from typing import Any

from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, Response


def generate_openapi_schema(request: Request) -> dict[str, Any]:
    """Generate a comprehensive OpenAPI 3.0 schema for all API and MCP routes."""
    base_url = str(request.base_url).rstrip("/")
    
    return {
        "openapi": "3.0.3",
        "info": {
            "title": "Internal AI MCP Bridge API",
            "version": "1.1.0",
            "description": (
                "Complete API documentation for the Internal AI MCP Bridge. "
                "This bridge exposes both standard REST API endpoints and MCP (Model Context Protocol) endpoints "
                "for interaction with an in-house AI platform. The service supports WebSocket connections for MCP, "
                "OpenAI-compatible chat endpoints, and memory/conversation management APIs."
            ),
            "contact": {
                "name": "API Support",
                "url": "https://github.com/AD-Archer/internal-ai-bridge-mcp"
            }
        },
        "servers": [
            {"url": base_url, "description": "Current server"}
        ],
        "tags": [
            {
                "name": "Health & Status",
                "description": "Health check and status endpoints"
            },
            {
                "name": "OpenAI Compatible",
                "description": "OpenAI-compatible chat completion endpoints"
            },
            {
                "name": "MCP Protocol",
                "description": "Model Context Protocol endpoints (WebSocket and HTTP)"
            },
            {
                "name": "Memory & Conversations",
                "description": "Conversation history and memory management"
            },
            {
                "name": "Callbacks",
                "description": "Callback endpoints for AI responses"
            }
        ],
        "paths": {
            "/": {
                "get": {
                    "tags": ["Health & Status"],
                    "summary": "Service information",
                    "description": "Returns basic information about the service and available endpoints",
                    "responses": {
                        "200": {
                            "description": "Service information",
                            "content": {
                                "text/plain": {
                                    "schema": {"type": "string"},
                                    "example": "external-ai MCP Bridge WebSocket endpoints at /mcp/openai and /mcp/hook."
                                }
                            }
                        }
                    }
                }
            },
            "/healthz": {
                "get": {
                    "tags": ["Health & Status"],
                    "summary": "Health check",
                    "description": "Returns the health status of the service",
                    "responses": {
                        "200": {
                            "description": "Service is healthy",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {
                                            "status": {
                                                "type": "string",
                                                "example": "ok"
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            },
            "/v1/models": {
                "get": {
                    "tags": ["OpenAI Compatible"],
                    "summary": "List available models",
                    "description": "Returns a list of available AI models in OpenAI format",
                    "responses": {
                        "200": {
                            "description": "List of models",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {
                                            "object": {
                                                "type": "string",
                                                "example": "list"
                                            },
                                            "data": {
                                                "type": "array",
                                                "items": {
                                                    "type": "object",
                                                    "properties": {
                                                        "id": {"type": "string"},
                                                        "object": {"type": "string"},
                                                        "created": {"type": "integer"},
                                                        "owned_by": {"type": "string"}
                                                    }
                                                }
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            },
            "/v1/chat/completions": {
                "post": {
                    "tags": ["OpenAI Compatible"],
                    "summary": "Create chat completion",
                    "description": "OpenAI-compatible chat completion endpoint. Send messages and receive AI responses.",
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "required": ["messages"],
                                    "properties": {
                                        "messages": {
                                            "type": "array",
                                            "description": "Array of message objects",
                                            "items": {
                                                "type": "object",
                                                "required": ["role", "content"],
                                                "properties": {
                                                    "role": {
                                                        "type": "string",
                                                        "enum": ["system", "user", "assistant"],
                                                        "description": "The role of the message author"
                                                    },
                                                    "content": {
                                                        "type": "string",
                                                        "description": "The content of the message"
                                                    }
                                                }
                                            }
                                        },
                                        "stream": {
                                            "type": "boolean",
                                            "default": False,
                                            "description": "Whether to stream the response"
                                        },
                                        "session_id": {
                                            "type": "string",
                                            "description": "Optional session ID for conversation tracking"
                                        }
                                    }
                                },
                                "example": {
                                    "messages": [
                                        {"role": "user", "content": "Hello, how are you?"}
                                    ]
                                }
                            }
                        }
                    },
                    "responses": {
                        "200": {
                            "description": "Successful response",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {
                                            "id": {"type": "string"},
                                            "object": {"type": "string"},
                                            "created": {"type": "integer"},
                                            "model": {"type": "string"},
                                            "choices": {
                                                "type": "array",
                                                "items": {
                                                    "type": "object",
                                                    "properties": {
                                                        "index": {"type": "integer"},
                                                        "message": {
                                                            "type": "object",
                                                            "properties": {
                                                                "role": {"type": "string"},
                                                                "content": {"type": "string"}
                                                            }
                                                        },
                                                        "finish_reason": {"type": "string"}
                                                    }
                                                }
                                            },
                                            "usage": {
                                                "type": "object",
                                                "properties": {
                                                    "prompt_tokens": {"type": "integer"},
                                                    "completion_tokens": {"type": "integer"},
                                                    "total_tokens": {"type": "integer"}
                                                }
                                            }
                                        }
                                    }
                                }
                            }
                        },
                        "400": {
                            "description": "Bad request",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {
                                            "error": {"type": "string"}
                                        }
                                    }
                                }
                            }
                        },
                        "500": {
                            "description": "Internal server error",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {
                                            "error": {"type": "string"}
                                        }
                                    }
                                }
                            }
                        },
                        "504": {
                            "description": "Gateway timeout",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {
                                            "error": {
                                                "type": "object",
                                                "properties": {
                                                    "message": {"type": "string"},
                                                    "type": {"type": "string"}
                                                }
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            },
            "/callback": {
                "post": {
                    "tags": ["Callbacks"],
                    "summary": "AI callback endpoint",
                    "description": "Endpoint for AI service to send follow-up messages and responses back to the bridge",
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "session_id": {
                                            "type": "string",
                                            "description": "Session identifier"
                                        },
                                        "message": {
                                            "type": "string",
                                            "description": "The AI response message"
                                        },
                                        "status": {
                                            "type": "string",
                                            "enum": ["info", "success", "error", "complete"],
                                            "description": "Status of the response"
                                        },
                                        "payload": {
                                            "type": "object",
                                            "description": "Additional payload data"
                                        }
                                    }
                                }
                            }
                        }
                    },
                    "responses": {
                        "200": {
                            "description": "Callback received successfully",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {
                                            "status": {"type": "string"},
                                            "session_id": {"type": "string"}
                                        }
                                    }
                                }
                            }
                        },
                        "400": {
                            "description": "Invalid request",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {
                                            "error": {"type": "string"}
                                        }
                                    }
                                }
                            }
                        },
                        "500": {
                            "description": "Internal server error",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {
                                            "error": {"type": "string"}
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            },
            "/conversations": {
                "get": {
                    "tags": ["Memory & Conversations"],
                    "summary": "List conversations",
                    "description": "Get a list of recent conversation sessions",
                    "parameters": [
                        {
                            "name": "limit",
                            "in": "query",
                            "schema": {"type": "integer", "default": 100},
                            "description": "Maximum number of sessions to return"
                        }
                    ],
                    "responses": {
                        "200": {
                            "description": "List of conversation sessions",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {
                                            "sessions": {
                                                "type": "array",
                                                "items": {
                                                    "type": "object",
                                                    "properties": {
                                                        "session_id": {"type": "string"},
                                                        "message_count": {"type": "integer"},
                                                        "last_updated": {"type": "string"}
                                                    }
                                                }
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            },
            "/conversations/{session_id}": {
                "get": {
                    "tags": ["Memory & Conversations"],
                    "summary": "Get conversation details",
                    "description": "Retrieve all messages for a specific conversation session",
                    "parameters": [
                        {
                            "name": "session_id",
                            "in": "path",
                            "required": True,
                            "schema": {"type": "string"},
                            "description": "The session ID to retrieve"
                        }
                    ],
                    "responses": {
                        "200": {
                            "description": "Conversation details",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {
                                            "session_id": {"type": "string"},
                                            "messages": {
                                                "type": "array",
                                                "items": {
                                                    "type": "object",
                                                    "properties": {
                                                        "role": {"type": "string"},
                                                        "content": {"type": "string"},
                                                        "metadata": {"type": "object"},
                                                        "created_at": {"type": "string"}
                                                    }
                                                }
                                            }
                                        }
                                    }
                                }
                            }
                        },
                        "404": {
                            "description": "Session not found",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {
                                            "error": {"type": "string"}
                                        }
                                    }
                                }
                            }
                        }
                    }
                },
                "delete": {
                    "tags": ["Memory & Conversations"],
                    "summary": "Delete conversation",
                    "description": "Delete a conversation session and all its messages",
                    "parameters": [
                        {
                            "name": "session_id",
                            "in": "path",
                            "required": True,
                            "schema": {"type": "string"},
                            "description": "The session ID to delete"
                        }
                    ],
                    "responses": {
                        "200": {
                            "description": "Conversation deleted successfully",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {
                                            "status": {"type": "string"},
                                            "session_id": {"type": "string"}
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            },
            "/memory/recall": {
                "get": {
                    "tags": ["Memory & Conversations"],
                    "summary": "Recall conversation memory (GET)",
                    "description": "Retrieve formatted conversation context and history via GET request",
                    "parameters": [
                        {
                            "name": "session_id",
                            "in": "query",
                            "schema": {"type": "string"},
                            "description": "Session ID to recall"
                        },
                        {
                            "name": "limit",
                            "in": "query",
                            "schema": {"type": "integer"},
                            "description": "Maximum number of messages to include"
                        }
                    ],
                    "responses": {
                        "200": {
                            "description": "Memory context retrieved",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {
                                            "session_id": {"type": "string"},
                                            "messages": {"type": "array"},
                                            "context_block": {"type": "string"},
                                            "user_messages": {
                                                "type": "array",
                                                "items": {"type": "string"}
                                            },
                                            "assistant_messages": {
                                                "type": "array",
                                                "items": {"type": "string"}
                                            },
                                            "message_count": {"type": "integer"},
                                            "limit_applied": {"type": "integer"}
                                        }
                                    }
                                }
                            }
                        }
                    }
                },
                "post": {
                    "tags": ["Memory & Conversations"],
                    "summary": "Recall conversation memory (POST)",
                    "description": "Retrieve formatted conversation context and history via POST request with optional parameters in body",
                    "requestBody": {
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "session_id": {
                                            "type": "string",
                                            "description": "Session ID to recall"
                                        },
                                        "limit": {
                                            "type": "integer",
                                            "description": "Maximum number of messages to include"
                                        }
                                    }
                                }
                            }
                        }
                    },
                    "responses": {
                        "200": {
                            "description": "Memory context retrieved or health check",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "oneOf": [
                                            {
                                                "type": "object",
                                                "properties": {
                                                    "status": {"type": "string"},
                                                    "requires_session_id": {"type": "boolean"},
                                                    "message": {"type": "string"}
                                                }
                                            },
                                            {
                                                "type": "object",
                                                "properties": {
                                                    "session_id": {"type": "string"},
                                                    "messages": {"type": "array"},
                                                    "context_block": {"type": "string"},
                                                    "message_count": {"type": "integer"}
                                                }
                                            }
                                        ]
                                    }
                                }
                            }
                        }
                    }
                }
            },
            "/mcp/openapi.json": {
                "get": {
                    "tags": ["MCP Protocol"],
                    "summary": "MCP OpenAPI schema",
                    "description": "Returns OpenAPI schema for MCP WebSocket endpoints",
                    "responses": {
                        "200": {
                            "description": "OpenAPI schema",
                            "content": {
                                "application/json": {
                                    "schema": {"type": "object"}
                                }
                            }
                        }
                    }
                }
            },
            "/mcp/hook": {
                "post": {
                    "tags": ["MCP Protocol"],
                    "summary": "MCP Memory HTTP endpoint",
                    "description": "HTTP endpoint for MCP protocol using JSON-RPC. Supports memory tools and conversation management.",
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "required": ["jsonrpc", "method"],
                                    "properties": {
                                        "jsonrpc": {
                                            "type": "string",
                                            "enum": ["2.0"],
                                            "description": "JSON-RPC version"
                                        },
                                        "method": {
                                            "type": "string",
                                            "enum": [
                                                "initialize",
                                                "tools/list",
                                                "tools/call",
                                                "resources/list",
                                                "resources/read"
                                            ],
                                            "description": "MCP method to call"
                                        },
                                        "params": {
                                            "type": "object",
                                            "description": "Method parameters"
                                        },
                                        "id": {
                                            "description": "Request identifier (omit for notifications)"
                                        }
                                    }
                                },
                                "examples": {
                                    "initialize": {
                                        "summary": "Initialize MCP connection",
                                        "value": {
                                            "jsonrpc": "2.0",
                                            "id": "1",
                                            "method": "initialize"
                                        }
                                    },
                                    "list_tools": {
                                        "summary": "List available tools",
                                        "value": {
                                            "jsonrpc": "2.0",
                                            "id": "2",
                                            "method": "tools/list"
                                        }
                                    },
                                    "call_tool": {
                                        "summary": "Call a tool",
                                        "value": {
                                            "jsonrpc": "2.0",
                                            "id": "3",
                                            "method": "tools/call",
                                            "params": {
                                                "name": "list_conversations",
                                                "arguments": {"limit": 10}
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    },
                    "responses": {
                        "200": {
                            "description": "JSON-RPC response",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {
                                            "jsonrpc": {"type": "string"},
                                            "id": {},
                                            "result": {
                                                "description": "Method result"
                                            },
                                            "error": {
                                                "type": "object",
                                                "properties": {
                                                    "code": {"type": "integer"},
                                                    "message": {"type": "string"}
                                                }
                                            }
                                        }
                                    }
                                }
                            }
                        },
                        "204": {
                            "description": "Notification received (no response body)"
                        },
                        "400": {
                            "description": "Invalid request"
                        },
                        "404": {
                            "description": "Method not found"
                        },
                        "405": {
                            "description": "Method not allowed"
                        }
                    }
                }
            },
            "/mcp/memory": {
                "post": {
                    "tags": ["MCP Protocol"],
                    "summary": "MCP Memory HTTP endpoint (alias)",
                    "description": "Alternative HTTP endpoint for MCP memory protocol (same as /mcp/hook)",
                    "requestBody": {
                        "$ref": "#/paths/~1mcp~1hook/post/requestBody"
                    },
                    "responses": {
                        "$ref": "#/paths/~1mcp~1hook/post/responses"
                    }
                }
            }
        },
        "components": {
            "schemas": {},
            "securitySchemes": {
                "BearerAuth": {
                    "type": "http",
                    "scheme": "bearer",
                    "description": "Optional Bearer token authentication (when ENABLE_BEARER_AUTH=true)"
                }
            }
        },
        "x-mcp-websockets": {
            "description": "The following WebSocket endpoints are available for MCP protocol connections",
            "endpoints": [
                {
                    "path": "/mcp/openai",
                    "description": "Primary MCP WebSocket endpoint with full AI and memory capabilities",
                    "protocol": "MCP"
                },
                {
                    "path": "/mcp/hook",
                    "description": "Memory-focused MCP WebSocket endpoint",
                    "protocol": "MCP"
                },
                {
                    "path": "/mcp/memory",
                    "description": "Memory MCP WebSocket endpoint (alias of /mcp/hook)",
                    "protocol": "MCP"
                }
            ],
            "tools": [
                {
                    "name": "start_ai_message",
                    "description": "Send a prompt to the AI service",
                    "available_on": ["/mcp/openai"]
                },
                {
                    "name": "list_conversations",
                    "description": "List recent conversation sessions",
                    "available_on": ["/mcp/openai", "/mcp/hook", "/mcp/memory"]
                },
                {
                    "name": "get_conversation",
                    "description": "Get messages for a specific session",
                    "available_on": ["/mcp/openai", "/mcp/hook", "/mcp/memory"]
                },
                {
                    "name": "recall_conversation_context",
                    "description": "Get formatted context block for a session",
                    "available_on": ["/mcp/openai", "/mcp/hook", "/mcp/memory"]
                },
                {
                    "name": "delete_conversation",
                    "description": "Delete a conversation session",
                    "available_on": ["/mcp/openai", "/mcp/hook", "/mcp/memory"]
                },
                {
                    "name": "send_user_response",
                    "description": "Send response back to user/OpenWebUI",
                    "available_on": ["/mcp/openai", "/mcp/hook", "/mcp/memory"]
                }
            ]
        }
    }


def generate_swagger_html() -> str:
    """Generate Swagger UI HTML page."""
    return """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Internal AI MCP Bridge - API Documentation</title>
    <link rel="stylesheet" type="text/css" href="https://unpkg.com/swagger-ui-dist@5.11.0/swagger-ui.css">
    <style>
        html {
            box-sizing: border-box;
            overflow: -moz-scrollbars-vertical;
            overflow-y: scroll;
        }
        *, *:before, *:after {
            box-sizing: inherit;
        }
        body {
            margin: 0;
            padding: 0;
        }
        .swagger-ui .topbar {
            background-color: #1b1b1b;
        }
        .swagger-ui .info .title {
            color: #3b4151;
        }
    </style>
</head>
<body>
    <div id="swagger-ui"></div>
    <script src="https://unpkg.com/swagger-ui-dist@5.11.0/swagger-ui-bundle.js"></script>
    <script src="https://unpkg.com/swagger-ui-dist@5.11.0/swagger-ui-standalone-preset.js"></script>
    <script>
        window.onload = function() {
            const ui = SwaggerUIBundle({
                url: "./openapi.json",
                dom_id: '#swagger-ui',
                deepLinking: true,
                presets: [
                    SwaggerUIBundle.presets.apis,
                    SwaggerUIStandalonePreset
                ],
                plugins: [
                    SwaggerUIBundle.plugins.DownloadUrl
                ],
                layout: "StandaloneLayout",
                defaultModelsExpandDepth: 1,
                defaultModelExpandDepth: 1,
                docExpansion: "list",
                filter: true,
                showExtensions: true,
                showCommonExtensions: true
            });
            window.ui = ui;
        };
    </script>
</body>
</html>
"""


async def swagger_ui_handler(request: Request) -> Response:
    """Serve the Swagger UI HTML page."""
    html = generate_swagger_html()
    return HTMLResponse(html)


async def openapi_json_handler(request: Request) -> Response:
    """Serve the comprehensive OpenAPI JSON schema."""
    schema = generate_openapi_schema(request)
    return JSONResponse(schema)
