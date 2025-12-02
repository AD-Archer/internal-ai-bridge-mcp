# Internal AI MCP Bridge

This project exposes a Model Context Protocol (MCP) bridge so OpenWebUI (or any MCP-capable client such as an n8n flow) can talk to an in-house AI platform that is reachable via HTTP webhooks. The bridge publishes MCP tools and resources that map directly onto the webhook workflows.

## Features
- `start_ai_message` tool sends user prompts to your AI webhook and returns the generated response.
- `trigger_webhook` tool calls any configured outbound webhook (e.g. n8n nodes, Slack notifications).
- `call_ai_and_webhook` tool combines both steps for the common "ask AI then notify" pattern.
- Resource `external-ai://webhooks` lists available webhook aliases so clients can discover them.
- Ships with both stdio (for OpenWebUI desktop adapters) and WebSocket transports.
- Conversation transcripts are persisted in SQLite so each `sessionID` keeps its own memory and can be inspected later.
- Dedicated `/memory/recall` endpoint (GET or POST) lets downstream AI services pull the latest context for any `sessionID` on demand.
- **Automatic retry** on 5xx errors and timeouts with exponential backoff (up to 3 attempts).
- Provides a lightweight OpenAPI document at `/mcp/openapi.json` for clients that probe HTTP metadata.

## Quick Start
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
cp .env.example .env
# edit .env with your webhook URLs/secrets
external-ai stdio --env-file .env
```

When running with `stdio`, connect OpenWebUI’s MCP integration to the spawned process. For a standalone WebSocket endpoint:

```bash
external-ai websocket --env-file .env --host 0.0.0.0 --port 8765
```

Alternatively, you can run the project directly with uvicorn (exposes the same
WebSocket/HTTP endpoints). The package ships an ASGI entrypoint at
`external-ai_mcp.asgi:app` which will try to load settings from the environment
or a `.env` file (set `ENV_FILE` to point at a dotenv file if you prefer).

Example using uvicorn:

```bash
# after creating & activating the venv and installing
uvicorn external-ai_mcp.asgi:app --host 0.0.0.0 --port 8765 --reload

# or specify an explicit dotenv file to load before starting
ENV_FILE=.env uvicorn external-ai_mcp.asgi:app --host 0.0.0.0 --port 8765
```

## Docker
- Build locally: `docker build -t external-ai-mcp .`
- Run: `docker run --rm -p 8765:8765 --env-file .env -v "$(pwd)/conversation_history.db:/app/conversation_history.db" external-ai-mcp`
- The image loads environment from `/app/.env` by default (`ENV_FILE` can override). Mount your `.env` or pass env vars directly.
- Published image (via GitHub Actions): `ghcr.io/ad-archer/external-ai-bridge-mcp:latest` (also tagged per branch, tag, and commit SHA).

### Docker Compose example
```yaml
services:
  external-ai-bridge:
    image: ghcr.io/ad-archer/external-ai-bridge-mcp:latest
    restart: unless-stopped
    env_file:
      - .env
    # environment:
      # Override defaults if you prefer not to use .env
      # AI_WEBHOOK_URL: https://your-ai-service.internal/webhooks/start
      # MODEL_NAME: your-custom-model-name
      # PORT: "8765"
      # ENV_FILE: /app/.env
      # CONVERSATION_DB_PATH: /app/data/conversation_history.db
    ports:
      - "8765:8765"
    volumes:
      - ./data:/app/data
      # Optional: mount a custom env file inside the container
      # - ./prod.env:/app/.env:ro
```

## Configuration
All settings are provided via environment variables (loadable from a `.env` file).

| Variable | Required | Description |
| --- | --- | --- |
| `AI_WEBHOOK_URL` | ✅ | Full URL of the in-house AI webhook that accepts JSON payloads. |
| `AI_API_KEY` | optional | Secret added as a `Bearer` token when reaching the AI webhook. |
| `AI_TIMEOUT` | optional | Request timeout in seconds (defaults to 30). |
| `CONVERSATION_DB_PATH` | optional | Filesystem path to the SQLite DB that stores session transcripts (`./conversation_history.db` by default). |
| `CONVERSATION_HISTORY_LIMIT` | optional | Max number of prior messages to feed back into each AI prompt (defaults to 20). |
| `ENABLE_BEARER_AUTH` | optional | When `true`, every route except `/healthz` requires a valid `Authorization: Bearer ...` header (defaults to `false`). |
| `API_BEARER_TOKEN` | optional | Shared Bearer token used for any protected route that does not have an explicit override. |
| `ROUTE_BEARER_TOKENS` | optional | JSON object that maps specific path prefixes (e.g. `/v1`, `/mcp/hook`) to dedicated Bearer tokens. |
| `EXTRA_WEBHOOKS` | optional | JSON object describing named webhook targets. |

Example `EXTRA_WEBHOOKS` value:

```json
{
  "n8n_status": {
    "url": "https://n8n.example.com/webhook/status",
    "method": "POST",
    "headers": {"x-api-key": "secret"},
    "secret": "optional-shared-secret"
  },
  "slack_alert": {
    "url": "https://hooks.slack.com/services/...",
    "method": "POST"
  }
}
```

Each webhook entry becomes available to the `trigger_webhook` tool as the `target` name. Headers declared in the config are merged with any headers supplied by the MCP client at call time. If `secret` is set it is sent as an `X-Webhook-Secret` header.

When bearer auth is enabled you can either rely on a single `API_BEARER_TOKEN` for every route, or override select prefixes via `ROUTE_BEARER_TOKENS`. For example:

```json
{
  "/mcp/hook": "memory-hook-token",
  "/v1": "openai-endpoints-token"
}
```

The overrides apply to both HTTP and WebSocket routes whose path matches or extends the provided prefix.

## Configuration
All settings are provided via environment variables (loadable from a `.env` file).

## MCP Surface

| Name | Type | Purpose |
| --- | --- | --- |
| `start_ai_message` | Tool | `{prompt, conversation_id?, metadata?, attachments?, extra?}` → calls the AI webhook. |
| `trigger_webhook` | Tool | `{target/name or URL, payload?, method?, headers?}` → triggers named or ad-hoc webhooks. |
| `call_ai_and_webhook` | Tool | Convenience wrapper that chains `start_ai_message` then (optionally) `trigger_webhook`. |
| `list_conversations` | Tool | `{limit?}` → returns recent conversation sessions from memory. |
| `get_conversation` | Tool | `{session_id, limit?}` → retrieves messages for a specific session. |
| `recall_conversation_context` | Tool | `{session_id, limit?}` → returns formatted context block for a session. |
| `delete_conversation` | Tool | `{session_id}` → removes a conversation session. |
| `record_ai_response` | Tool | `{session_id?, message?, payload?, role?, status?}` → saves AI/tool responses via the memory MCP (preferred over `/callback`). |
| `external-ai://webhooks` | Resource | JSON summary of configured webhook aliases for discovery. |
| `external-ai://messages` | Resource | JSON list of follow-up messages captured by `record_ai_response` (or the legacy `/callback`). |
| `memory://sessions` | Resource | JSON list of conversation sessions. |
| `memory://health` | Resource | Health status of the memory service. |

## Recording AI Follow-Ups
The recommended way to send responses back into the bridge is to call the `record_ai_response` MCP tool that ships with the memory server. It is available over stdio/WebSocket as well as JSON-RPC at `/mcp/hook` (alias `/mcp/memory`). This keeps everything inside the same MCP transport that downstream agents already use for recall.

Example JSON-RPC call over HTTP:

```bash
curl -X POST https://external-ai-test.archer.software/mcp/hook \
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

The tool automatically stores the message, keeps the metadata payload, and notifies any waiting OpenAI-compatible clients plus the optional `FRONTEND_WEBHOOK_URL`.

### Legacy `/callback`
If your AI stack cannot speak MCP yet, you can continue POSTing JSON to `/callback`. The same validation rules apply and the request is internally routed through `record_ai_response`, so both transports behave identically.

Expected payload structure (all fields optional):
```json
{
  "sessionID": "unique-session-id",
  "status": "info|success|error|complete",
  "payload_summary": "Brief summary",
  "message": "Full AI response",
  "next_step": "What happens next",
  "data": {}  // Optional structured data
}
```

Example request:
```bash
curl -X POST https://external-ai-test.yoururl/callback \
  -H "Content-Type: application/json" \
  -d '{"sessionID": "123", "status": "complete", "message": "Task done"}'
```

The MCP client can then read these messages via the `external-ai://messages` resource. The server only validates the `status` field if present.

The return values from tools are raw JSON dictionaries—structure them however your in-house AI responds. Errors from the webhook surface back to the MCP client as tool failures so the model can retry or ask for clarification.

## Conversation History API
Every call flowing through `/v1/chat/completions` (and the matching response recorded via `record_ai_response` or `/callback`) is stored in a lightweight SQLite database. This enables two behaviors:

1. Previous exchanges for the same `sessionID` are summarised and prepended when a new prompt is forwarded to your AI webhook, so the backend receives awareness of the running conversation.
2. Operators (or downstream AI services such as external-ai) can pull the history over HTTP, inspect it, or purge it.

Available endpoints:

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/conversations?limit=100` | Returns the most recently updated sessions plus message counts. |
| `GET` | `/conversations/{session_id}` | Dumps the stored messages (role, content, metadata, timestamps) for a session. |
| `DELETE` | `/conversations/{session_id}` | Removes a session and all of its messages. |
| `GET/POST` | `/memory/recall` | Returns a ready-to-use context block, broken-out user/assistant turns, and metadata for the requested `session_id`. |

`/memory/recall` accepts JSON **or** query parameters. If you call it without a session it simply replies `{"status":"healthy","requires_session_id":true,...}` so MCP clients can use it as a connectivity probe before they have real data. Example POST body (any of `sessionID`, `sessionId`, `session_id`, `conversationID`, or header `X-Session-ID` will be detected):

```json
{
  "sessionID": "2a5bad04-8f0b-4919-b663-88cc8d8e5e32",
  "limit": 20
}
```

GET example:

```
/memory/recall?sessionID=2a5bad04-8f0b-4919-b663-88cc8d8e5e32&limit=20
```

Response:

```json
{
  "session_id": "2a5bad04-8f0b-4919-b663-88cc8d8e5e32",
  "messages": [
    {"role": "user", "content": "tell me what you can do", "created_at": "..."},
    {"role": "assistant", "content": "I can ...", "created_at": "..."}
  ],
  "user_messages": ["tell me what you can do"],
  "assistant_messages": ["I can ..."],
  "context_block": "User: ...\nAssistant: ...",
  "message_count": 2,
  "limit_applied": 20
}
```

Downstream agents can hit this endpoint at the start of every task, feed the `context_block` into their workflow, and decide whether to trim/transform the `user_messages` or `assistant_messages` arrays. The endpoint is standalone (no webhook call required) so it works even if the agent cannot reach the original MCP webhook target.

Every `/memory/recall` request is logged with its method, query parameters, and whether a matching session was found—watch the service logs if you need to debug what Ninjacat is actually sending.

By default transcripts live in `./conversation_history.db`; adjust `CONVERSATION_DB_PATH` in your `.env` if you prefer a different location or persistent volume.

If you need the AI webhook to see fewer/more prior turns, change `CONVERSATION_HISTORY_LIMIT`. A higher number delivers more context but increases payload size.

## Connecting OpenWebUI
1. Run `external-ai stdio --env-file .env`.
2. In OpenWebUI, add a new MCP server and configure it to launch the CLI above (the desktop build uses stdio transports). Provide the same `.env` file in the launch command.
3. Once connected, the model will see the tools/resources listed above. Prompt the model to “use the start_ai_message tool” and it will forward the request to your webhook.

If you use the OpenWebUI MCP proxy (WebSocket transport), point it to `https://<host>:8765/mcp/openai` (subprotocol: `mcp`).

For HTTP-based MCP clients, use `https://<host>:8765/mcp/hook` (or `/mcp/memory`) with JSON-RPC 2.0 POST requests.

## Connecting n8n
- Add an HTTP Request or Webhook node that calls `http://localhost:8765/mcp` using the MCP WebSocket protocol (subprotocol `mcp`).
- Alternatively, expose n8n workflows as HTTP endpoints and register them inside `EXTRA_WEBHOOKS`. The MCP tools can then trigger those flows by name without n8n speaking MCP natively.
- Use the `trigger_webhook` tool to push AI results back into n8n after each inference.
- Add an HTTP Request or Webhook node that calls `http://localhost:8765/mcp` using the MCP WebSocket protocol (subprotocol `mcp`).
- Alternatively, expose n8n workflows as HTTP endpoints and register them inside `EXTRA_WEBHOOKS`. The MCP tools can then trigger those flows by name without n8n speaking MCP natively.
- Use the `trigger_webhook` tool to push AI results back into n8n after each inference.

## Development
- Run `./.venv/bin/python -m compileall src` to perform a quick syntax check.
- `ruff` and `pytest` are included in the optional `dev` extras (`pip install -e .[dev]`).
- Server wiring lives in `src/external-ai_mcp/server.py`; HTTP glue is in `src/external-ai_mcp/ai_client.py`.

## Next Steps
- Support streaming responses (SSE/Streamable HTTP) once available from the backend.
- Introduce authentication on the WebSocket endpoint before exposing it publicly.
