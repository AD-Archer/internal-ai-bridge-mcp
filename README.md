# Internal AI MCP Bridge

This project exposes a Model Context Protocol (MCP) bridge so OpenWebUI (or any MCP-capable client such as an n8n flow) can talk to an in-house AI platform reachable via HTTP webhooks.

## Demo

[![Video Demo](https://img.youtube.com/vi/5yb-jC34WKM/0.jpg)](https://www.youtube.com/watch?v=5yb-jC34WKM)

## What is an Internal AI

An internal AI is an AI use internally by an organization, school or business. This tools may be limited, or have sensitive information so this tool as as a bridge to allow for that AI to be used in open source tools like n8n for workflows. 

## Features
- `start_ai_message`, `trigger_webhook`, `call_ai_and_webhook` tools map prompts/webhook orchestration to your backend.
- stdio and WebSocket transports; OpenAI-compatible `/v1/chat/completions` endpoint.
- Conversation transcripts persisted in SQLite; `/memory/recall` to fetch context blocks per session.
- Resources for discovery (`external-ai://webhooks`, `external-ai://messages`, `memory://sessions`, `memory://health`).
- Automatic retry on 5xx/timeouts (up to 3 attempts) and lightweight OpenAPI at `/mcp/openapi.json`.

## Notice
- This bridge has to be hosted remotely or have ports 80/443 forwarded, or else you will not be able to receive messages back from your AI service. It is recommended to install tailscale and use tailscale serve, other solutions exist and are untested such as cloudflare tunnels.

## Quick Start (Docker)
Prepare config:
```bash
mkdir -p data
```
Minimum `.env` fields to update:
```
AI_WEBHOOK_URL=https://your-ai-service.internal/webhooks/start
MODEL_NAME=your-custom-model-name
CONVERSATION_DB_PATH=/app/data/conversation_history.db
```

Full `.env` template (copy/paste into your own file if you don't clone):
```
# Core AI webhook endpoint - This is where you send a webhook to your remote ai service, get this from the AI you intend to use, Ninjacat, Playlab, ETC
AI_WEBHOOK_URL=https://your-ai-service.internal/webhooks/start

# This is the name of your custom model
MODEL_NAME=your-custom-model-name

# Optional timeout in seconds (defaults to 30)
# AI_TIMEOUT=45

# Number of past messages to include when rebuilding context (defaults to 20)
CONVERSATION_HISTORY_LIMIT=20

# Number of days to retain messages before automatic deletion (defaults to 14)
MESSAGE_RETENTION_DAYS=14

# Optional bearer auth (disabled by default). When enabled, every route except /healthz
# requires a valid Authorization header. You can either share the default token across
# all routes or override specific prefixes via ROUTE_BEARER_TOKENS.

ENABLE_BEARER_AUTH=false
API_BEARER_TOKEN=shared-bearer-token

ROUTE_BEARER_TOKENS={
   "/mcp/hook": "memory-hook-token",
   "/v1": "openai-compatible-token"
 }
```

Run with Compose:
```bash
docker compose -f docker-compose.example.yml up -d
# or copy the example to docker-compose.yml first, then:
# docker compose up -d
```

Run with plain Docker:
```bash
docker run --rm -p 8765:8765 \
  --env-file .env \
  -v "$(pwd)/data:/app/data" \
  ghcr.io/ad-archer/external-ai-bridge-mcp:latest
```
- Container loads `/app/.env` by default (`ENV_FILE` can override).
- Default port is `8765`; override with `-e PORT=9000`.
 - Ensure `CONVERSATION_DB_PATH=/app/data/conversation_history.db` in your `.env` (default is set in the image) so the DB lands in the mounted volume.

## Quick Start (Local dev)
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .[dev]
cp .env.example .env
# edit .env, then:
external-ai websocket --env-file .env --host 0.0.0.0 --port 8765
```
Uvicorn entrypoint: `ENV_FILE=.env uvicorn external-ai_mcp.asgi:app --host 0.0.0.0 --port 8765 --reload`.

## Configuration reference
All settings come from environment variables (or a `.env` file).

| Variable | Required | Description |
| --- | --- | --- |
| `AI_WEBHOOK_URL` | ✅ | Full URL of the AI webhook that accepts JSON payloads. |
| `AI_API_KEY` | optional | Bearer token for the AI webhook. |
| `AI_TIMEOUT` | optional | Request timeout in seconds (default 30). |
| `CONVERSATION_DB_PATH` | optional | SQLite path (default `./conversation_history.db`). |
| `CONVERSATION_HISTORY_LIMIT` | optional | Past messages to include when rebuilding context (default 20). |
| `MESSAGE_RETENTION_DAYS` | optional | Days to retain messages (default 14). |
| `ENABLE_BEARER_AUTH` | optional | Protect routes with Bearer auth (default false). |
| `API_BEARER_TOKEN` | optional | Default Bearer token when auth is enabled. |
| `ROUTE_BEARER_TOKENS` | optional | JSON map of path prefixes to tokens. |
| `EXTRA_WEBHOOKS` | optional | JSON map of named webhook targets. |
| `FRONTEND_WEBHOOK_URL` | optional | Notifies a frontend when messages arrive. |

Example `EXTRA_WEBHOOKS`:
```json
{
  "n8n_status": {
    "url": "https://n8n.example.com/webhook/status",
    "method": "POST",
    "headers": {"x-api-key": "secret"},
    "secret": "optional-shared-secret"
  }
}
```

## MCP surface
| Name | Type | Purpose |
| --- | --- | --- |
| `start_ai_message` | Tool | `{prompt, conversation_id?, metadata?, attachments?, extra?}` → calls the AI webhook. |
| `trigger_webhook` | Tool | `{target/name or URL, payload?, method?, headers?}` → triggers named or ad-hoc webhooks. |
| `call_ai_and_webhook` | Tool | Chains AI call then optional webhook. |
| `list_conversations` | Tool | `{limit?}` → returns recent sessions. |
| `get_conversation` | Tool | `{session_id, limit?}` → retrieves messages for a session. |
| `recall_conversation_context` | Tool | `{session_id, limit?}` → formatted context block. |
| `delete_conversation` | Tool | `{session_id}` → removes a conversation session. |
| `record_ai_response` | Tool | `{session_id?, message?, payload?, role?, status?}` → saves responses (preferred over `/callback`). |
| `external-ai://webhooks` | Resource | Webhook aliases summary. |
| `external-ai://messages` | Resource | Follow-up messages captured by `record_ai_response` (or `/callback`). |
| `memory://sessions` | Resource | Conversation sessions list. |
| `memory://health` | Resource | Memory service health. |

## Recording AI follow-ups
Preferred path: call `record_ai_response` via MCP (stdio/WebSocket) or HTTP JSON-RPC at `/mcp/hook`.
```bash
curl -X POST https://your-host/mcp/hook \
  -H "Content-Type: application/json" \
  -d '{
        "jsonrpc":"2.0",
        "id":"1",
        "method":"tools/call",
        "params":{
          "name":"record_ai_response",
          "arguments":{
            "session_id":"123",
            "status":"complete",
            "message":"Task done",
            "payload":{"sessionID":"123","message":"Task done","status":"complete"}
          }
        }
      }'
```
Legacy `/callback` remains for HTTP-only stacks; payload mirrors the `record_ai_response` arguments.

## Conversation history API
Endpoints:
| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/conversations?limit=100` | Recent sessions plus counts. |
| `GET` | `/conversations/{session_id}` | Stored messages for a session. |
| `DELETE` | `/conversations/{session_id}` | Delete a session and its messages. |
| `GET/POST` | `/memory/recall` | Context block and metadata for a session. |

`/memory/recall` accepts JSON or query params; calling without a session returns `{"status":"healthy","requires_session_id":true,...}` for connectivity checks. Default DB path is `./conversation_history.db`; set `CONVERSATION_DB_PATH` (e.g., `/app/data/conversation_history.db`) when using volumes.

## Connecting OpenWebUI
1) Run the application.  
2) In OpenWebUI, add a new connection pointing to your host with route `/v1`.  
3) The model name comes from `MODEL_NAME` in `.env`.

## Connecting n8n
1) Add an OpenAI node; set Base URL to your host with route `/v1`.  
2) If bearer auth is enabled for `/v1`, supply the token as the API key.  
3) Use like any other OpenAI endpoint (tool use not exposed).

## Development
- `run_server.sh` will reinstall the package and start uvicorn with reload.
- Quick lint/syntax check: `python -m compileall src` (CI runs this).

## Next steps
- Support streaming responses (SSE/Streamable HTTP) once available.
- Standardize naming (internal vs external) across docs and configs.
