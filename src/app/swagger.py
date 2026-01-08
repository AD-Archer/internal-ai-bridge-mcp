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
                                    "example": "Internal AI MCP Bridge WebSocket endpoints at /mcp/openai and /mcp/hook."
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
    """Generate API documentation HTML page."""
    return """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Internal AI MCP Bridge - API Documentation</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        body {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
            line-height: 1.6;
            color: #333;
            background: #f5f5f5;
        }
        .header {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 2rem;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
        }
        .header h1 {
            font-size: 2rem;
            margin-bottom: 0.5rem;
        }
        .header p {
            opacity: 0.9;
            font-size: 1.1rem;
        }
        .container {
            max-width: 1200px;
            margin: 2rem auto;
            padding: 0 1rem;
        }
        .section {
            background: white;
            border-radius: 8px;
            padding: 2rem;
            margin-bottom: 2rem;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }
        .section h2 {
            color: #667eea;
            margin-bottom: 1rem;
            padding-bottom: 0.5rem;
            border-bottom: 2px solid #f0f0f0;
        }
        .endpoint {
            background: #f8f9fa;
            border-left: 4px solid #667eea;
            padding: 1rem;
            margin: 1rem 0;
            border-radius: 4px;
        }
        .endpoint-header {
            display: flex;
            align-items: center;
            margin-bottom: 0.5rem;
        }
        .method {
            padding: 0.25rem 0.75rem;
            border-radius: 4px;
            font-weight: bold;
            margin-right: 1rem;
            font-size: 0.85rem;
        }
        .method.get { background: #61affe; color: white; }
        .method.post { background: #49cc90; color: white; }
        .method.delete { background: #f93e3e; color: white; }
        .method.ws { background: #fca130; color: white; }
        .path {
            font-family: 'Courier New', monospace;
            font-weight: bold;
            color: #333;
        }
        .description {
            margin: 0.5rem 0;
            color: #666;
        }
        .json-link {
            display: inline-block;
            background: #667eea;
            color: white;
            padding: 0.75rem 1.5rem;
            border-radius: 6px;
            text-decoration: none;
            font-weight: 500;
            transition: background 0.3s;
        }
        .json-link:hover {
            background: #764ba2;
        }
        .info-box {
            background: #e3f2fd;
            border-left: 4px solid #2196f3;
            padding: 1rem;
            margin: 1rem 0;
            border-radius: 4px;
        }
        .mcp-tools {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
            gap: 1rem;
            margin-top: 1rem;
        }
        .tool-card {
            background: #f8f9fa;
            padding: 1rem;
            border-radius: 6px;
            border: 1px solid #e0e0e0;
        }
        .tool-card h4 {
            color: #667eea;
            margin-bottom: 0.5rem;
        }
    </style>
</head>
<body>
    <div class="header">
        <h1>🚀 Internal AI MCP Bridge API</h1>
        <p>Complete API documentation for AI and MCP routes</p>
    </div>
    
    <div class="container">
        <div class="section">
            <h2>📖 OpenAPI Specification</h2>
            <p>Access the complete OpenAPI 3.0 specification in JSON format:</p>
            <p style="margin-top: 1rem;">
                <a href="./openapi.json" class="json-link">📄 View OpenAPI JSON</a>
            </p>
            <div class="info-box" style="margin-top: 1rem;">
                <strong>📌 Note:</strong> This OpenAPI spec can be imported into tools like Postman, Insomnia, or any OpenAPI-compatible client.
            </div>
        </div>

        <div class="section">
            <h2>🏥 Health & Status</h2>
            <div class="endpoint">
                <div class="endpoint-header">
                    <span class="method get">GET</span>
                    <span class="path">/healthz</span>
                </div>
                <p class="description">Health check endpoint - returns service status</p>
            </div>
            <div class="endpoint">
                <div class="endpoint-header">
                    <span class="method get">GET</span>
                    <span class="path">/</span>
                </div>
                <p class="description">Service information and available endpoints</p>
            </div>
        </div>

        <div class="section">
            <h2>🤖 OpenAI Compatible API</h2>
            <div class="endpoint">
                <div class="endpoint-header">
                    <span class="method get">GET</span>
                    <span class="path">/v1/models</span>
                </div>
                <p class="description">List available AI models in OpenAI format</p>
            </div>
            <div class="endpoint">
                <div class="endpoint-header">
                    <span class="method post">POST</span>
                    <span class="path">/v1/chat/completions</span>
                </div>
                <p class="description">Create chat completions (OpenAI-compatible endpoint)</p>
            </div>
        </div>

        <div class="section">
            <h2>🔌 MCP Protocol Endpoints</h2>
            <div class="info-box">
                <strong>Model Context Protocol (MCP)</strong> endpoints support both WebSocket and HTTP JSON-RPC connections.
            </div>
            
            <div class="endpoint">
                <div class="endpoint-header">
                    <span class="method ws">WS</span>
                    <span class="path">/mcp/openai</span>
                </div>
                <p class="description">Primary MCP WebSocket endpoint with full AI and memory capabilities</p>
            </div>
            <div class="endpoint">
                <div class="endpoint-header">
                    <span class="method ws">WS</span>
                    <span class="path">/mcp/hook</span>
                </div>
                <p class="description">Memory-focused MCP WebSocket endpoint</p>
            </div>
            <div class="endpoint">
                <div class="endpoint-header">
                    <span class="method post">POST</span>
                    <span class="path">/mcp/hook</span>
                </div>
                <p class="description">HTTP endpoint for MCP protocol using JSON-RPC (memory tools)</p>
            </div>
            <div class="endpoint">
                <div class="endpoint-header">
                    <span class="method post">POST</span>
                    <span class="path">/mcp/memory</span>
                </div>
                <p class="description">Alternative HTTP endpoint for MCP memory protocol</p>
            </div>

            <h3 style="margin-top: 2rem; color: #667eea;">Available MCP Tools</h3>
            <div class="mcp-tools">
                <div class="tool-card">
                    <h4>list_conversations</h4>
                    <p>List recent conversation sessions from memory</p>
                </div>
                <div class="tool-card">
                    <h4>get_conversation</h4>
                    <p>Get all messages for a specific session</p>
                </div>
                <div class="tool-card">
                    <h4>recall_conversation_context</h4>
                    <p>Get formatted context block for a session</p>
                </div>
                <div class="tool-card">
                    <h4>delete_conversation</h4>
                    <p>Delete a conversation session and its messages</p>
                </div>
                <div class="tool-card">
                    <h4>send_user_response</h4>
                    <p>Send response back to user/OpenWebUI</p>
                </div>
                <div class="tool-card">
                    <h4>start_ai_message</h4>
                    <p>Send a prompt to the AI service (main endpoint only)</p>
                </div>
            </div>
        </div>

        <div class="section">
            <h2>💾 Memory & Conversations</h2>
            <div class="endpoint">
                <div class="endpoint-header">
                    <span class="method get">GET</span>
                    <span class="path">/conversations</span>
                </div>
                <p class="description">List all conversation sessions with metadata</p>
            </div>
            <div class="endpoint">
                <div class="endpoint-header">
                    <span class="method get">GET</span>
                    <span class="path">/conversations/{session_id}</span>
                </div>
                <p class="description">Retrieve all messages for a specific session</p>
            </div>
            <div class="endpoint">
                <div class="endpoint-header">
                    <span class="method delete">DELETE</span>
                    <span class="path">/conversations/{session_id}</span>
                </div>
                <p class="description">Delete a conversation session</p>
            </div>
            <div class="endpoint">
                <div class="endpoint-header">
                    <span class="method get">GET</span>
                    <span class="path">/memory/recall</span>
                </div>
                <p class="description">Recall conversation memory with formatted context</p>
            </div>
            <div class="endpoint">
                <div class="endpoint-header">
                    <span class="method post">POST</span>
                    <span class="path">/memory/recall</span>
                </div>
                <p class="description">Recall conversation memory via POST request</p>
            </div>
        </div>

        <div class="section">
            <h2>📞 Callbacks</h2>
            <div class="endpoint">
                <div class="endpoint-header">
                    <span class="method post">POST</span>
                    <span class="path">/callback</span>
                </div>
                <p class="description">Endpoint for AI service to send follow-up messages and responses</p>
            </div>
        </div>

        <div class="section">
            <h2>🔐 Authentication</h2>
            <div class="info-box">
                <p><strong>Bearer Token Authentication</strong> can be enabled via the <code>ENABLE_BEARER_AUTH</code> environment variable.</p>
                <p style="margin-top: 0.5rem;">When enabled, most routes require an <code>Authorization: Bearer &lt;token&gt;</code> header.</p>
                <p style="margin-top: 0.5rem;"><strong>Exempt routes:</strong> <code>/healthz</code>, <code>/docs</code>, <code>/openapi.json</code></p>
            </div>
        </div>
    </div>
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
