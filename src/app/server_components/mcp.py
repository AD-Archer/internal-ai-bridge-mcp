from __future__ import annotations

import json
import logging
from typing import Any

from mcp.server.fastmcp import FastMCP

from ..ai_client import AIWebhookClient, AIWebhookError
from ..config import Settings
from ..memory_api import register_memory_mcp_surface
from ..storage import ConversationStore
from .response_handler import build_response_handler
from .state import callback_messages

logger = logging.getLogger(__name__)


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

    response_handler = build_response_handler(settings)
    try:
        store = ConversationStore(settings.conversation_db_path)
        register_memory_mcp_surface(mcp, store, settings, response_handler=response_handler)
    except Exception as exc:  # pragma: no cover - defensive fallback
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
        except AIWebhookError as exc:  # pragma: no cover - passthrough
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


__all__ = ["build_server", "run_stdio"]
