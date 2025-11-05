# Model Context Protocol Bridge Architecture

## Goals
- expose an MCP server that OpenWebUI (or its n8n bridge) can talk to
- relay `createCompletion` style prompts and tool calls to an in-house AI platform that is driven by webhooks
- surface reusable webhook/n8n actions to the client through MCP actions and resources

## Components
- **OpenWebUI / n8n**: hosts the user-facing conversation interface; connects to the MCP server over WebSocket.
- **MCP Bridge Server**: a Python process implemented in this repo. It speaks the Model Context Protocol transport (stdio or WebSocket) and maps MCP `createMessage` / `callTool` requests onto backend workflows.
- **AI Webhook Backend**: an HTTP endpoint (supplied by the user) that kicks off or continues AI tasks. The bridge invokes this endpoint with the payload collected from MCP.
- **Optional Outbound Webhooks**: additional webhooks that can be triggered as MCP actions (eg. to push updates back into n8n).

## Message Flow
1. OpenWebUI emits an MCP `createMessage` request with user text.
2. Bridge server packages the request as a JSON payload and POSTs it to the configured AI webhook endpoint.
3. AI backend replies with generated text and optionally instructions for tool usage.
4. Bridge returns the response to OpenWebUI as `message` content. If tool calls are requested, it exposes them via MCP `callTool`.
5. Additional MCP actions (eg. `trigger_webhook`) allow OpenWebUI workflows to manipulate n8n or other services by HTTP.

## Configuration
- `AI_WEBHOOK_URL`: base URL for the in-house AI webhook that accepts JSON input and returns JSON output.
- `AI_API_KEY`: optional secret passed as a header when talking to the webhook.
- `EXTRA_WEBHOOKS`: JSON map that names additional webhook targets. Each entry can be used by the `trigger_webhook` MCP action.

## Transport Compatibility
- OpenWebUI prefers MCP over WebSocket. We expose a WebSocket listener at `ws://localhost:8765/mcp`.
- n8n can connect via HTTP/Webhook nodes. It can also invoke the outbound webhook action published by the MCP server.

## Error Handling
- Transform HTTP or network failures into structured MCP errors.
- Guard responses with schema validation to ensure the MCP client sees predictable data.

## Future Enhancements
- Cache conversation state in a database if the webhook backend does not.
- Support streaming responses via SSE or chunked WebSocket messages once the backend offers them.
- Add authentication and rate limiting middleware.
