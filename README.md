# Ninjacat MCP Bridge

This project exposes a Model Context Protocol (MCP) bridge so OpenWebUI (or any MCP-capable client such as an n8n flow) can talk to an in-house AI platform that is reachable via HTTP webhooks. The bridge publishes MCP tools and resources that map directly onto the webhook workflows.

## Features
- `start_ai_message` tool sends user prompts to your AI webhook and returns the generated response.
- `trigger_webhook` tool calls any configured outbound webhook (e.g. n8n nodes, Slack notifications).
- `call_ai_and_webhook` tool combines both steps for the common “ask AI then notify” pattern.
- Resource `ninjacat://webhooks` lists available webhook aliases so clients can discover them.
- Ships with both stdio (for OpenWebUI desktop adapters) and WebSocket transports.

## Quick Start
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
cp .env.example .env
# edit .env with your webhook URLs/secrets
ninjacat-mcp stdio --env-file .env
```

When running with `stdio`, connect OpenWebUI’s MCP integration to the spawned process. For a standalone WebSocket endpoint:

```bash
ninjacat-mcp websocket --env-file .env --host 0.0.0.0 --port 8765
```

Alternatively, you can run the project directly with uvicorn (exposes the same
WebSocket/HTTP endpoints). The package ships an ASGI entrypoint at
`ninjacat_mcp.asgi:app` which will try to load settings from the environment
or a `.env` file (set `ENV_FILE` to point at a dotenv file if you prefer).

Example using uvicorn:

```bash
# after creating & activating the venv and installing
uvicorn ninjacat_mcp.asgi:app --host 0.0.0.0 --port 8765 --reload

# or specify an explicit dotenv file to load before starting
ENV_FILE=.env uvicorn ninjacat_mcp.asgi:app --host 0.0.0.0 --port 8765
```

## Configuration
All settings are provided via environment variables (loadable from a `.env` file).

| Variable | Required | Description |
| --- | --- | --- |
| `AI_WEBHOOK_URL` | ✅ | Full URL of the in-house AI webhook that accepts JSON payloads. |
| `AI_API_KEY` | optional | Secret added as a `Bearer` token when reaching the AI webhook. |
| `AI_TIMEOUT` | optional | Request timeout in seconds (defaults to 30). |
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

## MCP Surface

| Name | Type | Purpose |
| --- | --- | --- |
| `start_ai_message` | Tool | `{prompt, conversation_id?, metadata?, attachments?, extra?}` → calls the AI webhook. |
| `trigger_webhook` | Tool | `{target/name or URL, payload?, method?, headers?}` → triggers named or ad-hoc webhooks. |
| `call_ai_and_webhook` | Tool | Convenience wrapper that chains `start_ai_message` then (optionally) `trigger_webhook`. |
| `ninjacat://webhooks` | Resource | JSON summary of configured webhook aliases for discovery. |

The return values from tools are raw JSON dictionaries—structure them however your in-house AI responds. Errors from the webhook surface back to the MCP client as tool failures so the model can retry or ask for clarification.

## Connecting OpenWebUI
1. Run `ninjacat-mcp stdio --env-file .env`.
2. In OpenWebUI, add a new MCP server and configure it to launch the CLI above (the desktop build uses stdio transports). Provide the same `.env` file in the launch command.
3. Once connected, the model will see the tools/resources listed above. Prompt the model to “use the start_ai_message tool” and it will forward the request to your webhook.

If you use the OpenWebUI MCP proxy (WebSocket transport), point it to `ws://<host>:8765/mcp` after launching `ninjacat-mcp websocket`.

## Connecting n8n
- Add an HTTP Request or Webhook node that calls `http://localhost:8765/mcp` using the MCP WebSocket protocol (subprotocol `mcp`).
- Alternatively, expose n8n workflows as HTTP endpoints and register them inside `EXTRA_WEBHOOKS`. The MCP tools can then trigger those flows by name without n8n speaking MCP natively.
- Use the `trigger_webhook` tool to push AI results back into n8n after each inference.

## Development
- Run `./.venv/bin/python -m compileall src` to perform a quick syntax check.
- `ruff` and `pytest` are included in the optional `dev` extras (`pip install -e .[dev]`).
- Server wiring lives in `src/ninjacat_mcp/server.py`; HTTP glue is in `src/ninjacat_mcp/ai_client.py`.

## Next Steps
- Add persistence for conversation state if the AI webhook expects incremental messages.
- Support streaming responses (SSE/Streamable HTTP) once available from the backend.
- Introduce authentication on the WebSocket endpoint before exposing it publicly.
